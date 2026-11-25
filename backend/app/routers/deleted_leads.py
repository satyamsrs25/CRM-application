"""Leads > Deleted Leads: restore leads that were deleted by mistake.

- Deleting a lead (one, or several at once) keeps a copy here: every field of the lead and its notes (keep_copy, called
  by routers/leads.py delete_one). Its tasks, emails and stage history are not kept.
- The Admin sees every deleted lead; a Manager the ones that were theirs, their team's or in the Unassigned Pool, and
  the ones they or their team deleted. Salespeople don't see this list.
- Restore (one, several or all those ticked): each lead comes back with its fields and notes in the Unassigned Pool
  (no owner), with its old id when still free, so old links work again. A lead whose email is now on another lead
  (someone added the person again) is skipped and stays here, with the reason.
- A deleted lead can be restored for 90 days (KEEP_DAYS). After that its copy is deleted for good: by the background
  checks (app/scheduler.py, every minute) and before the list is shown or leads are restored.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime, Numeric, delete, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DeletedLead, Lead, Note, User
from app.security import Acting, acting_user, team_ids
from app.services import log_activity, now

router = APIRouter(prefix="/api/deleted-leads", tags=["Deleted Leads"])

SKIP_COLUMNS = {"id", "owner_id", "assigned_at"}  # a restored lead goes to the Unassigned Pool
KEEP_DAYS = 90  # a deleted lead can be restored for this many days, then it is deleted for good
RESTORED_NOTE = "Restored from Deleted Leads by "  # starts the note a restore adds (the AI Assistant finds restores by it)


def purge_expired(db: Session) -> int:
    """Deletes for good the copies older than KEEP_DAYS (they can no longer be restored). Returns how many."""
    result = db.execute(delete(DeletedLead).where(DeletedLead.deleted_at < now() - timedelta(days=KEEP_DAYS)))
    return result.rowcount or 0


def keep_copy(db: Session, lead: Lead, owner_name: str | None, actor_id: int) -> None:
    """Saves a copy of the lead and its notes before it is deleted."""
    fields = {c.key: getattr(lead, c.key) for c in Lead.__table__.columns if c.computed is None}
    notes = [{"body": n.body, "created_by_id": n.created_by_id, "created_at": n.created_at}
             for n in db.scalars(select(Note).where(Note.lead_id == lead.id).order_by(Note.id)).all()]
    db.add(DeletedLead(lead_id=lead.id, name=lead.name, company=lead.company, email=lead.email, stage=lead.stage,
                       owner_id=lead.owner_id, owner_name=owner_name, deleted_by_id=actor_id, deleted_at=now(),
                       data=json.dumps({"lead": fields, "notes": notes}, default=str)))


def _value(column, value):
    """A saved field back to its column's type (dates, amounts)."""
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    if isinstance(column.type, Numeric):
        return Decimal(value)
    return value


def _require_manager() -> Acting:
    me = acting_user()
    if not (me.is_admin or me.role == "Manager"):
        raise HTTPException(status_code=403, detail="Only the Admin and Managers can see and restore deleted leads")
    return me


def _visible(db: Session, me: Acting):
    """The deleted leads this person may see: the Admin all; a Manager their own, their team's and pooled ones."""
    query = select(DeletedLead)
    if not me.is_admin:
        people = team_ids(db, me.id) | {me.id}
        query = query.where(or_(DeletedLead.owner_id.in_(people), DeletedLead.owner_id.is_(None),
                                DeletedLead.deleted_by_id.in_(people)))
    return query


def _out(row: DeletedLead) -> dict:
    expires_at = row.deleted_at + timedelta(days=KEEP_DAYS) if row.deleted_at else None
    days_left = max(0, (expires_at.date() - now().date()).days) if expires_at else None
    return {"id": row.id, "lead_id": row.lead_id, "name": row.name, "company": row.company, "email": row.email,
            "stage": row.stage, "owner_name": row.owner_name or "Unassigned Pool",
            "deleted_by_name": row.deleted_by.full_name if row.deleted_by else None, "deleted_at": row.deleted_at,
            "expires_at": expires_at, "days_left": days_left}


@router.get("")
def list_deleted(search: str = Query("", max_length=100), page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Deleted leads of the last 90 days, newest first, a page at a time (search: name, company or email)."""
    me = _require_manager()
    if purge_expired(db):
        db.commit()
    query = _visible(db, me)
    words = search.strip()
    if words:
        like = f"%{words}%"
        query = query.where(or_(DeletedLead.name.ilike(like), DeletedLead.company.ilike(like),
                                DeletedLead.email.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(DeletedLead.deleted_at.desc(), DeletedLead.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_out(r) for r in rows], "total": total, "page": page, "page_size": page_size,
            "keep_days": KEEP_DAYS}


class RestoreIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


@router.post("/restore")
def restore(data: RestoreIn, db: Session = Depends(get_db)):
    """Restores the ticked deleted leads to the Unassigned Pool (with their notes). Returns what was restored and
    what was skipped, with the reason."""
    me = _require_manager()
    purge_expired(db)  # past 90 days: no longer restorable
    rows = {r.id: r for r in db.scalars(_visible(db, me).where(DeletedLead.id.in_(data.ids))).all()}
    restored, skipped = [], []
    columns = {c.key: c for c in Lead.__table__.columns}
    for row_id in dict.fromkeys(data.ids):
        row = rows.get(row_id)
        if row is None:
            skipped.append({"id": row_id, "name": None, "reason": "already restored or expired"})
            continue
        saved = json.loads(row.data)
        fields = {k: _value(columns[k], v) for k, v in saved["lead"].items() if k in columns and k not in SKIP_COLUMNS}
        email = (fields.get("email") or "").strip()
        if email:
            other = db.scalar(select(Lead).where(func.lower(Lead.email) == email.lower()).limit(1))
            if other is not None:
                skipped.append({"id": row_id, "name": row.name,
                                "reason": f"email used by {other.name}"})
                continue
        if fields.get("created_by_id") and db.get(User, fields["created_by_id"]) is None:
            fields["created_by_id"] = None
        lead = Lead(**fields, owner_id=None, assigned_at=None)
        if db.get(Lead, row.lead_id) is None:
            lead.id = row.lead_id  # old links to the lead work again
        db.add(lead)
        db.flush()
        for note in saved.get("notes", []):
            author = note.get("created_by_id")
            db.add(Note(lead_id=lead.id, body=note["body"], created_by_id=author if db.get(User, author) else me.id,
                        created_at=datetime.fromisoformat(note["created_at"]) if note.get("created_at") else None))
        db.add(Note(lead_id=lead.id, created_by_id=me.id,
                    body=f"{RESTORED_NOTE}{me.full_name} to the Unassigned Pool "
                         f"(deleted {row.deleted_at:%d %b %Y} by {row.deleted_by.full_name if row.deleted_by else 'someone'})."))
        log_activity(db, me.id, "Lead restored", row.name, "Back in the Unassigned Pool")
        db.delete(row)
        restored.append({"id": lead.id, "name": row.name})
    db.commit()
    return {"restored": restored, "skipped": skipped}
