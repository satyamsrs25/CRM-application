"""No-activity reminders: open leads and opportunities nobody has touched for IDLE_DAYS days.

A record is idle when, for IDLE_DAYS days, nothing happened on it: no change to the record (stage, fields, owner),
no note, no task added, changed or done, and no email sent. Only open records with an owner count (open lead stages,
open opportunity stages; the Unassigned Pool is not anyone's to follow up).

Once a day (from WORKDAY_START_HOUR, by the background checks in app/scheduler.py) each person gets ONE short summary
on the bell and by email (their Reminders email setting), never one message per record:
- Salesperson: the idle leads and opportunities they own
- Manager:     their own and their team's
- Admin:       everyone's
The summary replaces yesterday's, so the bell keeps one. It names the records that have waited longest and links to
Leads (or Opportunities) > No Activity (3+ Days), which lists them all.
"""
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.constants import LEAD_OPEN_STAGES, OPPORTUNITY_OPEN_STAGES, WORKDAY_START_HOUR
from app.models import Email, Lead, Note, Notification, Opportunity, Task, User
from app.services import notify, now, start_of_today

IDLE_DAYS = 3
IDLE_TITLE = "No activity for 3+ days"
IDLE_VIEW = "No Activity (3+ Days)"  # the list view (Leads and Opportunities) the summary links to
SHOWN = 4  # records named in a summary; the list view has the rest


def idle_condition(model, cutoff: datetime):
    """SQL: an open, owned lead or opportunity with no change, note, task or email since cutoff."""
    lead = model is Lead
    key = Note.lead_id if lead else Note.opportunity_id
    task_key = Task.lead_id if lead else Task.opportunity_id
    email_key = Email.lead_id if lead else Email.opportunity_id
    conditions = [
        model.stage.in_(LEAD_OPEN_STAGES if lead else OPPORTUNITY_OPEN_STAGES),
        model.owner_id.is_not(None),
        model.created_at < cutoff,
        or_(model.updated_at.is_(None), model.updated_at < cutoff),
        ~exists().where(key == model.id, Note.created_at >= cutoff),
        ~exists().where(task_key == model.id, or_(Task.created_at >= cutoff, Task.updated_at >= cutoff,
                                                  Task.completed_at >= cutoff)),
        ~exists().where(email_key == model.id, Email.sent_at >= cutoff),
    ]
    if lead:
        conditions.append(or_(Lead.assigned_at.is_(None), Lead.assigned_at < cutoff))
    return and_(*conditions)


def cutoff_now() -> datetime:
    return now() - timedelta(days=IDLE_DAYS)


def _last_activity(db: Session, record, lead: bool) -> datetime | None:
    """When something last happened on the record (for "idle since"), only for the few records named."""
    key = "lead_id" if lead else "opportunity_id"
    stamps = [record.updated_at, record.created_at, getattr(record, "assigned_at", None),
              db.scalar(select(func.max(Note.created_at)).where(getattr(Note, key) == record.id)),
              db.scalar(select(func.max(Task.updated_at)).where(getattr(Task, key) == record.id)),
              db.scalar(select(func.max(Email.sent_at)).where(getattr(Email, key) == record.id))]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _summary(db: Session, leads: list, opps: list, names: dict, *, show_owner: bool) -> tuple[str, str]:
    """The message and link of one person's summary."""
    def count(n, word):
        return f"{n:,} {word}{'' if n == 1 else 's'}"
    parts = [count(len(leads), "lead")] if leads else []
    if opps:
        parts.append(count(len(opps), "opportunity").replace("opportunitys", "opportunities"))
    verb = "has" if len(leads) + len(opps) == 1 else "have"
    lines = [f"{' and '.join(parts)} {verb} had no update or activity for {IDLE_DAYS}+ days. Please follow up."]
    rows = [("Lead", r, True) for r in leads] + [("Opportunity", r, False) for r in opps]
    rows.sort(key=lambda row: row[1].updated_at or row[1].created_at or datetime.min)
    for label, record, lead in rows[:SHOWN]:
        since = _last_activity(db, record, lead)
        extra = [f"Owner: {names.get(record.owner_id, 'someone')}"] if show_owner else []
        if since:
            extra.append(f"idle since {since:%d %b %Y}")
        company = f" ({record.company})" if lead and record.company else ""
        lines.append(f"{label}: {record.name}{company} · {' · '.join(extra)}" if extra else f"{label}: {record.name}{company}")
    if len(rows) > SHOWN:
        lines.append(f"…and {len(rows) - SHOWN:,} more in {IDLE_VIEW}.")
    query = f"?list={quote(IDLE_VIEW)}"
    link = f"/leads{query}" if leads else f"/opportunities{query}"
    return "\n".join(lines), link


def send_idle_reminders(db: Session) -> int:
    """Once a day from WORKDAY_START_HOUR: one summary per person who has idle records in their scope. Returns how
    many summaries were sent (0 before the start of the workday or when today's were already sent)."""
    current = now()
    if current.hour < WORKDAY_START_HOUR:
        return 0
    today = start_of_today()
    cutoff = current - timedelta(days=IDLE_DAYS)
    leads = db.scalars(select(Lead).where(idle_condition(Lead, cutoff))).all()
    opps = db.scalars(select(Opportunity).where(idle_condition(Opportunity, cutoff))).all()
    if not leads and not opps:
        return 0
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    names = {u.id: u.full_name for u in users}
    team = {}
    for u in users:
        if u.reports_to_id:
            team.setdefault(u.reports_to_id, set()).add(u.id)
    done_today = set(db.scalars(select(Notification.user_id).where(
        Notification.title == IDLE_TITLE, Notification.created_at >= today)).all())
    sent = 0
    for user in users:
        if user.id in done_today:
            continue
        if user.role == "Admin":
            scope = None  # everyone's
        elif user.role == "Manager":
            scope = team.get(user.id, set()) | {user.id}
        else:
            scope = {user.id}
        mine_leads = [r for r in leads if scope is None or r.owner_id in scope]
        mine_opps = [r for r in opps if scope is None or r.owner_id in scope]
        if not mine_leads and not mine_opps:
            continue
        others = any(r.owner_id != user.id for r in mine_leads + mine_opps)
        message, link = _summary(db, mine_leads, mine_opps, names, show_owner=others)
        for old in db.scalars(select(Notification).where(Notification.user_id == user.id,
                                                         Notification.title == IDLE_TITLE)).all():
            db.delete(old)  # the bell keeps only the latest summary
        notify(db, user.id, IDLE_TITLE, message, link=link, category="reminder",
               why="You get this daily summary because these records are yours or your team's to follow up.")
        sent += 1
    return sent


def idle_ids(db: Session, model, ids: list[int]) -> set[int]:
    """Which of these records are idle now (for the No Activity (3+ Days) list view)."""
    if not ids:
        return set()
    return set(db.scalars(select(model.id).where(model.id.in_(ids), idle_condition(model, cutoff_now()))).all())
