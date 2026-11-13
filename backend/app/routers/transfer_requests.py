"""Lead transfer requests: a user asks for a lead that belongs to someone else.

- Anyone but the Admin (who transfers leads directly) can ask for an open lead they don't own, with a reason. They can
  ask from the lead's page, or from the "email already in the CRM" message on a new lead (even for a lead they
  can't open).
- The lead's owner, the owner's Manager (Reports To) and the Admin are told. Any one of them approves or rejects it.
- Approval is mandatory: the lead moves to the requester only when it is approved. The move is a normal transfer
  (transfer history with the date and time, open follow-ups move, everyone is told). Other people's pending
  requests for the same lead are then closed.
- The requester can cancel a pending request.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.constants import LEAD_OPEN_STAGES
from app.database import get_db
from app.models import Lead, LeadTransferRequest, User
from app.routers.leads import transfer_lead
from app.security import acting_user, can_view, team_ids
from app.services import get_for_update, get_or_404, log_activity, notify

router = APIRouter(prefix="/api", tags=["Lead transfer requests"])


def approvers(db: Session, lead: Lead) -> list[User]:
    """Who can approve a request for this lead: its owner, the owner's Manager and every active Admin."""
    people = {lead.owner_id: lead.owner}
    if lead.owner and lead.owner.reports_to_id:
        manager = db.get(User, lead.owner.reports_to_id)
        if manager is not None:
            people[manager.id] = manager
    for admin in db.scalars(select(User).where(User.role == "Admin", User.is_active.is_(True))):
        people[admin.id] = admin
    return [p for p in people.values() if p is not None and p.is_active]


def can_decide(db: Session, lead: Lead) -> bool:
    me = acting_user()
    return me.is_admin or lead.owner_id == me.id or (lead.owner is not None and lead.owner.reports_to_id == me.id)


def request_out(db: Session, r: LeadTransferRequest) -> dict:
    me = acting_user()
    lead = r.lead
    pending = r.status == "Pending"
    return {
        "id": r.id, "status": r.status, "reason": r.reason, "created_at": r.created_at,
        "lead_id": lead.id, "lead_name": lead.name, "company": lead.company, "stage": lead.stage,
        "can_open_lead": can_view(lead.owner_id),
        "owner_id": lead.owner_id, "owner_name": lead.owner.full_name if lead.owner else None,
        "requested_by_id": r.requested_by_id, "requested_by_name": r.requested_by.full_name if r.requested_by else None,
        "decided_by_name": r.decided_by.full_name if r.decided_by else None, "decided_at": r.decided_at,
        "decision_note": r.decision_note,
        "can_decide": pending and can_decide(db, lead),
        "can_cancel": pending and r.requested_by_id == me.id,
    }


def pending_request(db: Session, lead_id: int, user_id: int) -> LeadTransferRequest | None:
    return db.scalars(select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead_id,
                                                        LeadTransferRequest.requested_by_id == user_id,
                                                        LeadTransferRequest.status == "Pending")).first()


@router.post("/leads/{lead_id}/transfer-requests", status_code=status.HTTP_201_CREATED)
def request_transfer(lead_id: int, data: schemas.TransferRequestCreate, db: Session = Depends(get_db)):
    """Ask for someone else's open lead to be transferred to you. Nothing changes until it is approved."""
    me = acting_user()
    lead = get_or_404(db, Lead, lead_id, "Lead")
    if me.is_admin:
        raise HTTPException(status_code=400, detail="The Admin transfers leads directly: use Transfer on the lead")
    if lead.owner_id == me.id:
        raise HTTPException(status_code=400, detail="This lead is already yours")
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"This lead is {lead.stage}: only open leads can be transferred")
    if pending_request(db, lead.id, me.id) is not None:
        raise HTTPException(status_code=409, detail="You have already asked for this lead. Wait for the answer, or cancel "
                                                    "your request.")
    request = LeadTransferRequest(lead_id=lead.id, requested_by_id=me.id, owner_id=lead.owner_id,
                                  reason=data.reason.strip())
    db.add(request)
    db.flush()
    requester = db.get(User, me.id)
    what = f'lead "{lead.name}" ({lead.company or "no company"})'
    for person in approvers(db, lead):
        whose = "your" if person.id == lead.owner_id else f"{lead.owner.full_name}'s"
        notify(db, person.id, "Lead transfer requested",
               f"{requester.full_name} asked for {whose} {what} to be transferred to them.\nReason: {request.reason}\n"
               "Approve or reject it under Leads > Transfer Requests.",
               link="/transfer-requests", category="assignment")
    log_activity(db, me.id, "Lead transfer requested", lead.name,
                 f"Owner: {lead.owner.full_name if lead.owner else '-'} • Reason: {request.reason}")
    db.commit()
    db.refresh(request)
    return request_out(db, request)


@router.get("/leads/{lead_id}/transfer-requests")
def lead_requests(lead_id: int, db: Session = Depends(get_db)):
    """The lead page: its requests (the owner, their Manager and the Admin see all of them; others only their own)."""
    me = acting_user()
    lead = get_or_404(db, Lead, lead_id, "Lead")
    query = select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead.id)
    if not can_decide(db, lead):
        query = query.where(LeadTransferRequest.requested_by_id == me.id)
    return [request_out(db, r) for r in db.scalars(query.order_by(LeadTransferRequest.id.desc())).all()]


@router.get("/transfer-requests")
def list_requests(box: str = Query("all", pattern="^(to_approve|mine|all)$"), db: Session = Depends(get_db)):
    """to_approve: pending requests you can approve. mine: the requests you made. all: both, newest first
    (the Admin: every request)."""
    me = acting_user()
    query = (select(LeadTransferRequest).join(Lead, Lead.id == LeadTransferRequest.lead_id)
             .options(selectinload(LeadTransferRequest.lead).selectinload(Lead.owner),
                      selectinload(LeadTransferRequest.requested_by), selectinload(LeadTransferRequest.decided_by)))
    team = team_ids(db, me.id)
    may_decide = or_(Lead.owner_id == me.id, Lead.owner_id.in_(team)) if team else Lead.owner_id == me.id
    if box == "mine":
        query = query.where(LeadTransferRequest.requested_by_id == me.id)
    elif box == "to_approve":
        query = query.where(LeadTransferRequest.status == "Pending")
        if not me.is_admin:
            query = query.where(may_decide)
    elif not me.is_admin:
        query = query.where(or_(LeadTransferRequest.requested_by_id == me.id, may_decide))
    rows = db.scalars(query.order_by(LeadTransferRequest.status != "Pending", LeadTransferRequest.id.desc())
                      .limit(500)).all()
    return [request_out(db, r) for r in rows]


def decided(db: Session, request_id: int) -> tuple[LeadTransferRequest, Lead]:
    request = get_for_update(db, LeadTransferRequest, request_id, "Transfer request")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"This request was already {request.status.lower()}")
    lead = get_for_update(db, Lead, request.lead_id, "Lead")
    return request, lead


def close(request: LeadTransferRequest, status_: str, note: str | None) -> None:
    request.status = status_
    request.decided_by_id = acting_user().id
    request.decided_at = datetime.now()
    request.decision_note = (note or "").strip() or None


@router.post("/transfer-requests/{request_id}/approve")
def approve(request_id: int, data: schemas.TransferRequestDecision, db: Session = Depends(get_db)):
    """The lead's owner, the owner's Manager or the Admin approves: the lead moves to the requester now."""
    me = acting_user()
    request, lead = decided(db, request_id)
    if not can_decide(db, lead):
        raise HTTPException(status_code=403, detail="Only the lead's owner, their Manager or the Admin can approve this")
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"This lead is {lead.stage} now: only open leads can be transferred. "
                                                    "Reject the request instead.")
    close(request, "Approved", data.note)
    note = f"Transfer request approved by {me.full_name}. Reason: {request.reason}"
    if request.decision_note:
        note += f" • {request.decision_note}"
    if request.requested_by_id != lead.owner_id:
        transfer_lead(db, lead, request.requested_by_id, note[:300], me.id)
    # anyone else waiting for this lead: closed (it has just been given away)
    for other in db.scalars(select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead.id,
                                                              LeadTransferRequest.status == "Pending",
                                                              LeadTransferRequest.id != request.id)).all():
        close(other, "Rejected", f"The lead was transferred to {request.requested_by.full_name}")
        notify(db, other.requested_by_id, "Lead transfer request rejected",
               f'Your request for lead "{lead.name}" was closed: it was transferred to {request.requested_by.full_name}.',
               link="/transfer-requests", category="assignment")
    log_activity(db, me.id, "Lead transfer approved", lead.name, f"To: {request.requested_by.full_name}")
    db.commit()
    db.refresh(request)
    return request_out(db, request)


@router.post("/transfer-requests/{request_id}/reject")
def reject(request_id: int, data: schemas.TransferRequestDecision, db: Session = Depends(get_db)):
    """The lead's owner, the owner's Manager or the Admin says no (with a reason). The lead stays where it is."""
    me = acting_user()
    request, lead = decided(db, request_id)
    if not can_decide(db, lead):
        raise HTTPException(status_code=403, detail="Only the lead's owner, their Manager or the Admin can reject this")
    if not (data.note or "").strip():
        raise HTTPException(status_code=422, detail="Say why the request is rejected")
    close(request, "Rejected", data.note)
    notify(db, request.requested_by_id, "Lead transfer request rejected",
           f'{me.full_name} rejected your request for lead "{lead.name}".\nReason: {request.decision_note}',
           link="/transfer-requests", category="assignment")
    log_activity(db, me.id, "Lead transfer rejected", lead.name,
                 f"Asked by: {request.requested_by.full_name} • Reason: {request.decision_note}")
    db.commit()
    db.refresh(request)
    return request_out(db, request)


@router.post("/transfer-requests/{request_id}/cancel")
def cancel(request_id: int, db: Session = Depends(get_db)):
    """The requester takes the request back."""
    me = acting_user()
    request, lead = decided(db, request_id)
    if request.requested_by_id != me.id:
        raise HTTPException(status_code=403, detail="Only the person who asked can cancel this request")
    close(request, "Cancelled", None)
    log_activity(db, me.id, "Lead transfer request cancelled", lead.name)
    db.commit()
    db.refresh(request)
    return request_out(db, request)
