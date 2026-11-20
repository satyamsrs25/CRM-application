"""Lead transfer requests: a user asks for a lead that belongs to someone else.

- Anyone but the Admin (who transfers leads directly) can ask for an open lead they don't own, with a reason. They can
  ask from the lead's page, or from the "email already in the CRM" message on a new lead (even for a lead they
  can't open).
- The lead's owner, the owner's Manager (Reports To) and the Admin are told. Any one of them approves or rejects it.
- Approval is mandatory: the lead moves to the requester only when it is approved. The move is a normal transfer
  (transfer history with the date and time, open follow-ups move, everyone is told). Other people's pending
  requests for the same lead are then closed.
- The requester can cancel a pending request.

The Unassigned Pool (leads with no owner, e.g. every bulk upload) uses the same requests:
- Only Salespeople ask for a pooled lead, with a reason, one lead or several selected at once (one reason for all; each
  lead still gets its own request, decided on its own). Asking gives no ownership and no edit rights.
- A pooled lead has no team, so the request goes by the requester's team: the Admin, or the requester's Manager
  (Reports To) when that Manager has Reassign owner, approves or rejects it. Whoever uploaded the lead has no say.
- Approval assigns the lead to the requester (routers/leads.py assign_from_pool) and closes everyone else's requests
  for it; a request whose lead was assigned meanwhile can't be approved any more (409), so nobody's owner is
  overwritten.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.constants import LEAD_OPEN_STAGES
from app.database import get_db
from app.models import Lead, LeadTransferRequest, User
from app.routers.leads import assign_from_pool, pool_conflict, pool_recipient, transfer_lead
from app.security import acting_user, can_view, manages_pool, team_ids, user_permissions
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


def can_decide(db: Session, lead: Lead, request: LeadTransferRequest | None = None) -> bool:
    me = acting_user()
    if is_pool_request(request) or (request is None and lead.owner_id is None):
        # a pooled lead: the Admin, or the requester's own Manager when they may assign pooled leads
        return me.is_admin or (request is not None and manages_pool(me) and request.requested_by is not None
                               and request.requested_by.reports_to_id == me.id)
    return me.is_admin or lead.owner_id == me.id or (lead.owner is not None and lead.owner.reports_to_id == me.id)


def is_pool_request(request: LeadTransferRequest | None) -> bool:
    """Asked for while the lead was in the Unassigned Pool (it had no owner)."""
    return request is not None and request.owner_id is None


def pool_approvers(db: Session, requester: User) -> list[User]:
    """Who can approve a request for a pooled lead: every active Admin, and the requester's active Manager when that
    Manager has Reassign owner. Nobody else (not whoever uploaded the lead)."""
    people = {a.id: a for a in db.scalars(select(User).where(User.role == "Admin", User.is_active.is_(True)))}
    manager = db.get(User, requester.reports_to_id) if requester.reports_to_id else None
    if (manager is not None and manager.is_active and manager.role == "Manager"
            and "reassign_owner" in user_permissions(db, manager)):
        people[manager.id] = manager
    return list(people.values())


def request_out(db: Session, r: LeadTransferRequest) -> dict:
    me = acting_user()
    lead = r.lead
    pending = r.status == "Pending"
    return {
        "id": r.id, "status": r.status, "reason": r.reason, "created_at": r.created_at,
        "lead_id": lead.id, "lead_name": lead.name, "company": lead.company, "stage": lead.stage,
        # a pooled lead opens for everyone (without its contact details for those who can only request it)
        "can_open_lead": lead.owner_id is None or can_view(lead.owner_id),
        "owner_id": lead.owner_id, "owner_name": lead.owner.full_name if lead.owner else None,
        "pool": is_pool_request(r),  # asked for from the Unassigned Pool
        "requested_by_id": r.requested_by_id, "requested_by_name": r.requested_by.full_name if r.requested_by else None,
        "decided_by_name": r.decided_by.full_name if r.decided_by else None, "decided_at": r.decided_at,
        "decision_note": r.decision_note,
        "can_decide": pending and can_decide(db, lead, r),
        "can_cancel": pending and r.requested_by_id == me.id,
    }


def pending_request(db: Session, lead_id: int, user_id: int) -> LeadTransferRequest | None:
    return db.scalars(select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead_id,
                                                        LeadTransferRequest.requested_by_id == user_id,
                                                        LeadTransferRequest.status == "Pending")).first()


@router.post("/leads/{lead_id}/transfer-requests", status_code=status.HTTP_201_CREATED)
def request_transfer(lead_id: int, data: schemas.TransferRequestCreate, db: Session = Depends(get_db)):
    """Ask for someone else's open lead to be transferred to you, or for a lead in the Unassigned Pool (Salespeople).
    Nothing changes until it is approved."""
    me = acting_user()
    lead = get_or_404(db, Lead, lead_id, "Lead")
    if lead.owner_id is None:
        return request_pool_lead(db, lead_id, data)
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
               link=f"/transfer-requests?request={request.id}", category="assignment")
    log_activity(db, me.id, "Lead transfer requested", lead.name,
                 f"Owner: {lead.owner.full_name if lead.owner else '-'} • Reason: {request.reason}")
    db.commit()
    db.refresh(request)
    return request_out(db, request)


ALREADY_ASKED = "You have already asked for this lead. Wait for the answer, or cancel your request."


def ensure_pool_requester(me) -> None:
    if me.role != "Salesperson":
        raise HTTPException(status_code=400, detail="Only Salespeople request leads from the Unassigned Pool. "
                                                    + ("Use Assign instead." if manages_pool(me) else
                                                       "The Admin or a Manager assigns them."))


def add_pool_request(db: Session, lead: Lead, requester_id: int, reason: str) -> LeadTransferRequest:
    """One request for a pooled lead the caller has locked (get_for_update), or HTTPException saying why not: assigned
    meanwhile (409), not open (400), or already asked for by this person (409)."""
    if lead.owner_id is not None:
        raise pool_conflict(lead)
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"This lead is {lead.stage}: only open leads can be requested")
    if pending_request(db, lead.id, requester_id) is not None:
        raise HTTPException(status_code=409, detail=ALREADY_ASKED)
    request = LeadTransferRequest(lead_id=lead.id, requested_by_id=requester_id, owner_id=None, reason=reason)
    db.add(request)
    db.flush()
    return request


def pool_routing(db: Session, requester: User) -> dict:
    """Who decides this person's requests for pooled leads, said plainly for the requester (the same people
    pool_approvers notifies and can_decide lets decide)."""
    people = pool_approvers(db, requester)
    manager = next((p for p in people if p.role == "Manager"), None)
    if manager is not None:
        note = f"Sent to your Manager, {manager.full_name}, and the Admin. Either of them can approve or reject each request."
    elif requester.reports_to_id is None:
        note = ("Sent to the Admin only: you have no Manager in Reports To. If your Manager should decide, ask the Admin "
                "to set your Reports To (Manage Access > People).")
    else:
        note = ("Sent to the Admin only: your Manager can't assign leads from the pool (inactive, or without the "
                "\"Reassign owner\" permission).")
    return {"sent_to": [p.full_name for p in people], "routing": note}


def request_pool_lead(db: Session, lead_id: int, data: schemas.TransferRequestCreate) -> dict:
    """A Salesperson asks for a lead in the Unassigned Pool, with a reason. It is not theirs (no edit rights) until
    the Admin or their Manager approves it. The deciders are told once, with a link to this request."""
    me = acting_user()
    ensure_pool_requester(me)
    lead = get_for_update(db, Lead, lead_id, "Lead")  # one request at a time per lead, and never once it is assigned
    request = add_pool_request(db, lead, me.id, data.reason.strip())
    requester = db.get(User, me.id)
    for person in pool_approvers(db, requester):
        notify(db, person.id, "Lead requested from the Unassigned Pool",
               f'{requester.full_name} asked for lead "{lead.name}" ({lead.company or "no company"}) from the '
               f"Unassigned Pool.\nReason: {request.reason}\nApprove or reject it under Leads > Transfer Requests.",
               link=f"/transfer-requests?request={request.id}", category="assignment")
    log_activity(db, me.id, "Lead requested from the Unassigned Pool", lead.name, f"Reason: {request.reason}")
    db.commit()
    db.refresh(request)
    return request_out(db, request) | pool_routing(db, requester)


@router.post("/transfer-requests/bulk")
def request_pool_leads(data: schemas.PoolRequestBulk, db: Session = Depends(get_db)):
    """A Salesperson asks for several selected leads from the Unassigned Pool, with one reason. Each lead gets its own
    request (approved or rejected on its own, with its own history); nothing is assigned. Leads already asked for,
    assigned since they were selected, closed or not found are listed and not requested. Up to 500 leads, only the ones
    sent (never the whole pool). The deciders get one summary each, not one notice per lead."""
    me = acting_user()
    ensure_pool_requester(me)
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Say why you should get these leads")
    created, skipped, conflicts = [], [], []
    for lead_id in sorted(set(data.lead_ids)):  # locked in id order, so two bulk requests never wait on each other
        lead = db.get(Lead, lead_id, with_for_update=True, populate_existing=True)
        if lead is None:
            skipped.append({"lead_id": lead_id, "name": f"Lead {lead_id}", "reason": "Not found"})
            continue
        try:
            request = add_pool_request(db, lead, me.id, reason)
        except HTTPException as exc:
            row = {"lead_id": lead.id, "name": lead.name}
            if lead.owner_id == me.id:  # e.g. one of their own leads ticked beside pooled ones
                skipped.append(row | {"reason": "This lead is already yours"})
            elif lead.owner_id is not None:
                conflicts.append(row | {"reason": "No longer in the Unassigned Pool: assigned since you selected it"})
            else:
                skipped.append(row | {"reason": "You have already asked for this lead" if exc.detail == ALREADY_ASKED
                                      else str(exc.detail)})
            continue
        created.append({"id": request.id, "lead_id": lead.id, "name": lead.name})
    requester = db.get(User, me.id)
    if created:
        count = len(created)
        names = ", ".join(c["name"] for c in created[:10]) + (f" and {count - 10} more" if count > 10 else "")
        one = count == 1
        for person in pool_approvers(db, requester):
            notify(db, person.id, "Lead requested from the Unassigned Pool" if one else "Leads requested from the Unassigned Pool",
                   f"{requester.full_name} asked for {'lead' if one else f'{count} leads'} from the Unassigned Pool: "
                   f"{names}.\nReason: {reason}\nApprove or reject {'it' if one else 'each one'} under Leads > Transfer Requests.",
                   link=f"/transfer-requests?request={created[0]['id']}" if one else "/transfer-requests?box=to_approve",
                   category="assignment")
        log_activity(db, me.id, "Leads requested from the Unassigned Pool", f"{count} lead{'' if one else 's'}",
                     f"{names} • Reason: {reason}" + (f" • {len(skipped) + len(conflicts)} not requested"
                                                     if skipped or conflicts else ""))
    db.commit()
    return {"requested": len(created), "created": created, "skipped": skipped, "conflicts": conflicts,
            **pool_routing(db, requester)}


@router.get("/leads/{lead_id}/transfer-requests")
def lead_requests(lead_id: int, db: Session = Depends(get_db)):
    """The lead page: its requests (the owner, their Manager and the Admin see all of them; others only their own).
    A pooled lead: the Admin sees all of them, a Manager their team's, everyone their own."""
    me = acting_user()
    lead = get_or_404(db, Lead, lead_id, "Lead")
    query = select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead.id)
    rows = db.scalars(query.order_by(LeadTransferRequest.id.desc())).all()
    if lead.owner_id is None or any(is_pool_request(r) for r in rows):
        team = team_ids(db, me.id)
        return [request_out(db, r) for r in rows if r.requested_by_id == me.id or me.is_admin
                or (is_pool_request(r) and manages_pool(me) and r.requested_by_id in team)
                or (not is_pool_request(r) and can_decide(db, lead, r))]
    if not can_decide(db, lead):
        rows = [r for r in rows if r.requested_by_id == me.id]
    return [request_out(db, r) for r in rows]


def box_conditions(db: Session, me, box: str) -> list:
    """Which requests a box holds for this user (the same rules for the list, its page, its counts and the Requested By
    choices). to_approve: pending requests you may decide. mine: the requests you made. all: both (the Admin: every
    request)."""
    team = team_ids(db, me.id)
    may_decide = or_(Lead.owner_id == me.id, Lead.owner_id.in_(team)) if team else Lead.owner_id == me.id
    if team and manages_pool(me):  # requests for pooled leads from the Manager's own Salespeople
        may_decide = or_(may_decide, and_(LeadTransferRequest.owner_id.is_(None),
                                          LeadTransferRequest.requested_by_id.in_(team)))
    if box == "mine":
        return [LeadTransferRequest.requested_by_id == me.id]
    if box == "to_approve":
        return [LeadTransferRequest.status == "Pending"] + ([] if me.is_admin else [may_decide])
    return [] if me.is_admin else [or_(LeadTransferRequest.requested_by_id == me.id, may_decide)]


BOX = Query("all", pattern="^(to_approve|mine|all)$")
ORDER = (LeadTransferRequest.status != "Pending", LeadTransferRequest.id.desc())  # pending first, newest first


def box_query(conditions: list):
    return (select(LeadTransferRequest).join(Lead, Lead.id == LeadTransferRequest.lead_id).where(*conditions)
            .options(selectinload(LeadTransferRequest.lead).selectinload(Lead.owner),
                     selectinload(LeadTransferRequest.requested_by), selectinload(LeadTransferRequest.decided_by)))


@router.get("/transfer-requests")
def list_requests(box: str = BOX, db: Session = Depends(get_db)):
    """to_approve: pending requests you can approve. mine: the requests you made. all: both, newest first
    (the Admin: every request). Up to 500; the Transfer Requests page uses /transfer-requests/page."""
    me = acting_user()
    rows = db.scalars(box_query(box_conditions(db, me, box)).order_by(*ORDER).limit(500)).all()
    return [request_out(db, r) for r in rows]


PAGE_MAX = schemas.BULK_DECISION_MAX  # a page never holds more requests than one bulk decision may take


@router.get("/transfer-requests/page")
def requests_page(box: str = BOX,
                  requested_by_id: int | None = Query(None, description="Only the requests this person made"),
                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=PAGE_MAX),
                  focus: int | None = Query(None, description="A request to show (e.g. from a notification): its page"),
                  db: Session = Depends(get_db)):
    """The Transfer Requests page, one page at a time. Requested By filters the whole box before it is paged, so
    `total` counts every matching request, not just the loaded ones. `requesters` are the people with requests in this
    box (with how many each), the only choices the filter offers: nobody the user can't already see there."""
    me = acting_user()
    conditions = box_conditions(db, me, box)
    counted = (select(LeadTransferRequest.requested_by_id, func.count())
               .join(Lead, Lead.id == LeadTransferRequest.lead_id).where(*conditions)
               .group_by(LeadTransferRequest.requested_by_id))
    counts = dict(db.execute(counted).all())
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_(counts))).all()) if counts else {}
    requesters = sorted(({"id": uid, "name": names.get(uid, "Unknown user"), "count": n} for uid, n in counts.items()),
                        key=lambda p: p["name"].lower())
    box_total = sum(counts.values())
    if requested_by_id is not None:
        conditions = [*conditions, LeadTransferRequest.requested_by_id == requested_by_id]
    total = counts.get(requested_by_id, 0) if requested_by_id is not None else box_total
    if focus is not None:  # the page that holds this request, when it is in this (filtered) box
        ids = db.scalars(select(LeadTransferRequest.id).join(Lead, Lead.id == LeadTransferRequest.lead_id)
                         .where(*conditions).order_by(*ORDER)).all()
        if focus in ids:
            offset = ids.index(focus) // limit * limit
    rows = db.scalars(box_query(conditions).order_by(*ORDER).offset(offset).limit(limit)).all()
    return {"box": box, "items": [request_out(db, r) for r in rows], "total": total, "box_total": box_total,
            "offset": offset, "limit": limit, "requested_by_id": requested_by_id, "requesters": requesters}


def decided(db: Session, request_id: int) -> tuple[LeadTransferRequest, Lead]:
    """The pending request and its lead, both locked. The lead is locked first: two people deciding requests for the
    same lead then go one after the other (the second sees the first one's result) instead of blocking each other."""
    found = get_or_404(db, LeadTransferRequest, request_id, "Transfer request")
    lead = get_for_update(db, Lead, found.lead_id, "Lead")
    request = get_for_update(db, LeadTransferRequest, request_id, "Transfer request")
    if request.status != "Pending":
        who = f" by {request.decided_by.full_name}" if request.decided_by else ""
        why = f": {request.decision_note}" if request.decision_note else ""
        raise HTTPException(status_code=409, detail=f"This request was already {request.status.lower()}{who}{why}")
    return request, lead


def close(request: LeadTransferRequest, status_: str, note: str | None) -> None:
    request.status = status_
    request.decided_by_id = acting_user().id
    request.decided_at = datetime.now()
    request.decision_note = (note or "").strip() or None


# ---------- deciding: one request, or the ones ticked in To Approve (the same rules for both) ----------

def approve_one(db: Session, request_id: int, note: str | None) -> LeadTransferRequest:
    """Approves one request (not committed): the lead moves to the requester, or a pooled lead is assigned to them.
    Raises HTTPException (nothing changed) when it can't: 404 not found, 403 not yours to decide, 409 decided or
    changed meanwhile (decided by someone else, the pooled lead assigned, or the lead's owner changed since it was
    asked for), 400 the lead is closed or the requester can't take it."""
    me = acting_user()
    request, lead = decided(db, request_id)
    if is_pool_request(request):
        approve_pool_request(db, request, lead, note)
        return request
    if not can_decide(db, lead):
        raise HTTPException(status_code=403, detail="Only the lead's owner, their Manager or the Admin can approve this")
    if lead.owner_id not in (request.owner_id, request.requested_by_id):
        # the lead was transferred since it was asked for: approving now would take it from its new owner
        raise HTTPException(status_code=409, detail="The lead's owner changed since this request (it now belongs to "
                                                    f"{lead.owner.full_name if lead.owner else 'someone else'}). Reject "
                                                    "the request, or the requester can ask again.")
    if lead.stage not in LEAD_OPEN_STAGES:
        raise HTTPException(status_code=400, detail=f"This lead is {lead.stage} now: only open leads can be transferred. "
                                                    "Reject the request instead.")
    close(request, "Approved", note)
    text = f"Transfer request approved by {me.full_name}. Reason: {request.reason}"
    if request.decision_note:
        text += f" • {request.decision_note}"
    if request.requested_by_id != lead.owner_id:
        transfer_lead(db, lead, request.requested_by_id, text[:300], me.id, request_id=request.id)
    # anyone else waiting for this lead: closed (it has just been given away)
    for other in db.scalars(select(LeadTransferRequest).where(LeadTransferRequest.lead_id == lead.id,
                                                              LeadTransferRequest.status == "Pending",
                                                              LeadTransferRequest.id != request.id)).all():
        close(other, "Rejected", f"The lead was transferred to {request.requested_by.full_name}")
        notify(db, other.requested_by_id, "Lead transfer request rejected",
               f'Your request for lead "{lead.name}" was closed: it was transferred to {request.requested_by.full_name}.',
               link="/transfer-requests", category="assignment")
    log_activity(db, me.id, "Lead transfer approved", lead.name, f"To: {request.requested_by.full_name}")
    return request


def approve_pool_request(db: Session, request: LeadTransferRequest, lead: Lead, note: str | None) -> None:
    """The Admin or the requester's Manager approves a request for a pooled lead: it is assigned to the requester."""
    me = acting_user()
    if not can_decide(db, lead, request):
        raise HTTPException(status_code=403, detail="Only the Admin, or the Manager the requester reports to (with "
                                                    "Reassign owner), can approve this")
    if lead.owner_id is not None:  # assigned meanwhile: this request can't change the owner
        raise pool_conflict(lead)
    requester = request.requested_by
    if requester is None or not requester.is_active or requester.role != "Salesperson":
        raise HTTPException(status_code=400, detail=f"{requester.full_name if requester else 'The requester'} is no "
                                                    "longer an active Salesperson. Reject the request instead.")
    target = pool_recipient(db, requester.id)
    close(request, "Approved", note)
    text = f"Request approved by {me.full_name}. Reason: {request.reason}"
    if request.decision_note:
        text += f" • {request.decision_note}"
    assign_from_pool(db, lead, target, me.id, text[:300], request=request)
    log_activity(db, me.id, "Lead request approved", lead.name, f"From the Unassigned Pool to {target.full_name}")


REJECT_REASON_REQUIRED = "Say why the request is rejected"


def reject_one(db: Session, request_id: int, note: str | None) -> LeadTransferRequest:
    """Rejects one request with a reason (not committed). The lead stays where it is; the requester is told."""
    me = acting_user()
    request, lead = decided(db, request_id)
    if not can_decide(db, lead, request):
        raise HTTPException(status_code=403, detail="Only the lead's owner, their Manager or the Admin can reject this")
    if not (note or "").strip():
        raise HTTPException(status_code=422, detail=REJECT_REASON_REQUIRED)
    close(request, "Rejected", note)
    pool = is_pool_request(request)
    notify(db, request.requested_by_id, "Lead request rejected" if pool else "Lead transfer request rejected",
           f'{me.full_name} rejected your request for lead "{lead.name}"{" from the Unassigned Pool" if pool else ""}.'
           f"\nReason: {request.decision_note}",
           link=f"/transfer-requests?request={request.id}", category="assignment")
    log_activity(db, me.id, "Lead transfer rejected", lead.name,
                 f"Asked by: {request.requested_by.full_name} • Reason: {request.decision_note}")
    return request


@router.post("/transfer-requests/{request_id}/approve")
def approve(request_id: int, data: schemas.TransferRequestDecision, db: Session = Depends(get_db)):
    """The lead's owner, the owner's Manager or the Admin approves: the lead moves to the requester now."""
    request = approve_one(db, request_id, data.note)
    db.commit()
    db.refresh(request)
    return request_out(db, request)


@router.post("/transfer-requests/{request_id}/reject")
def reject(request_id: int, data: schemas.TransferRequestDecision, db: Session = Depends(get_db)):
    """The lead's owner, the owner's Manager or the Admin says no (with a reason). The lead stays where it is."""
    request = reject_one(db, request_id, data.note)
    db.commit()
    db.refresh(request)
    return request_out(db, request)


@router.post("/transfer-requests/bulk-decision")
def decide_many(data: schemas.TransferRequestBulkDecision, db: Session = Depends(get_db)):
    """Approve or reject the requests ticked in To Approve, with one note (required to reject), by the Admin or a
    Manager. Only the ids sent are decided (up to 100), never a whole filter. Each one goes through the same checks
    as deciding it alone (approve_one / reject_one: who may decide it, still pending, lead still open and with the
    same owner, a pooled lead still unassigned), under its own locks and its own save, so one that can't be decided
    changes nothing and doesn't stop the others. Each decided request keeps its own history, Activity Log line and
    the requester's notification, exactly as a single decision; nothing is sent for one that wasn't decided.
    Results: done (approved or rejected), conflicts (decided or changed by someone else meanwhile: nothing was
    overwritten) and skipped (not allowed, or not possible now), each with the reason. Sending the same ids twice
    decides nothing the second time: they are no longer pending (conflicts)."""
    me = acting_user()
    if me.role not in ("Admin", "Manager"):
        raise HTTPException(status_code=403, detail="Only the Admin or a Manager approves or rejects requests in bulk. "
                                                    "Approve or reject each request on its own.")
    note = (data.note or "").strip() or None
    if data.decision == "reject" and not note:
        raise HTTPException(status_code=422, detail=REJECT_REASON_REQUIRED)
    decide = approve_one if data.decision == "approve" else reject_one
    done, conflicts, skipped = [], [], []
    for request_id in sorted(set(data.request_ids)):  # one at a time, in id order (each locks its lead, then itself)
        found = db.get(LeadTransferRequest, request_id)
        row = {"id": request_id, "lead_id": found.lead_id if found else None,
               "lead_name": found.lead.name if found and found.lead else f"Request {request_id}",
               "requested_by_name": found.requested_by.full_name if found and found.requested_by else None}
        try:
            request = decide(db, request_id, note)
            db.commit()  # this request's decision, history, notifications and emails (sent once it is saved)
        except HTTPException as exc:
            db.rollback()  # nothing of this one is kept or sent
            (conflicts if exc.status_code == 409 else skipped).append(row | {"reason": str(exc.detail)})
            continue
        done.append(row | {"status": request.status})
    count = len(done)
    return {"decision": data.decision, "approved" if data.decision == "approve" else "rejected": count,
            "done": done, "conflicts": conflicts, "skipped": skipped}


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
