"""Accurate numbers for the AI Assistant's statistics and reports: counted in the database (never from a capped list),
over the records the user may see (their own, or the team's with "View team records").

crm_report(period=..., owner_id=...) returns leads, opportunities and tasks figures for a period, plus a snapshot of
what is open right now. Amounts are in each deal's own currency (see "currency"). Rates are percentages with one decimal.
"""
import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.constants import LEAD_OPEN_STAGES, LEAD_STAGES, OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES
from app.models import Lead, LeadTransfer, Opportunity, Task, User
from app.security import acting_user
from app.services import BUSINESS_TIMEZONE, BUSINESS_TZ_NAME

PERIODS = ["today", "this_week", "last_week", "this_month", "last_month", "this_quarter", "last_quarter",
           "this_year", "last_year", "last_7_days", "last_30_days", "last_90_days", "all_time"]


def period_range(period: str | None, date_from: str | None = None, date_to: str | None = None,
                 today: date | None = None) -> tuple[datetime | None, datetime | None, str]:
    """(start, end, label): start inclusive, end exclusive. Explicit dates win over the period name.
    Periods that run up to now ("today", "this month", "last 30 days"...) have no end, so nothing created today is
    missed, whichever clock (the app's or the database's) stamped it."""
    today = today or date.today()
    if date_from or date_to:
        try:
            start = datetime.combine(date.fromisoformat(date_from[:10]), time()) if date_from else None
            end = datetime.combine(date.fromisoformat(date_to[:10]) + timedelta(days=1), time()) if date_to else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Dates must look like 2026-11-30") from exc
        return start, end, f"{date_from or 'the start'} to {date_to or 'today'}"
    period = period or "all_time"
    if period not in PERIODS:
        raise HTTPException(status_code=400, detail=f"Unknown period. Use one of: {', '.join(PERIODS)}")
    day = lambda d: datetime.combine(d, time())  # noqa: E731
    month_start = today.replace(day=1)
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    week_start = today - timedelta(days=today.weekday())
    if period == "all_time":
        return None, None, "all time"
    if period == "today":
        return day(today), None, "today"
    if period == "this_week":
        return day(week_start), None, "this week"
    if period == "last_week":
        return day(week_start - timedelta(days=7)), day(week_start), "last week"
    if period == "this_month":
        return day(month_start), None, f"{today:%B %Y} so far"
    if period == "last_month":
        prev = (month_start - timedelta(days=1)).replace(day=1)
        return day(prev), day(month_start), f"{prev:%B %Y}"
    if period == "this_quarter":
        return day(quarter_start), None, f"Q{(today.month - 1) // 3 + 1} {today.year} so far"
    if period == "last_quarter":
        prev = (quarter_start - timedelta(days=1))
        prev_start = date(prev.year, 3 * ((prev.month - 1) // 3) + 1, 1)
        return day(prev_start), day(quarter_start), f"Q{(prev.month - 1) // 3 + 1} {prev.year}"
    if period == "this_year":
        return day(date(today.year, 1, 1)), None, f"{today.year} so far"
    if period == "last_year":
        return day(date(today.year - 1, 1, 1)), day(date(today.year, 1, 1)), str(today.year - 1)
    days = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}[period]
    return day(today - timedelta(days=days - 1)), None, f"the last {days} days"


def _scope(query, model, owner_id: int | None):
    me = acting_user()
    if not me.sees_team:
        query = query.where(model.owner_id == me.id)
    if owner_id is not None:
        query = query.where(model.owner_id == owner_id)
    return query


def _between(query, column, start, end):
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column < end)
    return query


def _rate(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _money(value) -> float:
    return round(float(value or 0), 2)


def crm_report(db: Session, *, period: str | None = None, date_from: str | None = None, date_to: str | None = None,
               owner_id: int | None = None) -> dict:
    start, end, label = period_range(period, date_from, date_to)
    names = dict(db.execute(select(User.id, User.full_name)).all())

    def count(query) -> int:
        return db.scalar(query) or 0

    def by(column, model, extra=(), when=None):
        query = _scope(select(column, func.count()).select_from(model), model, owner_id)
        for condition in extra:
            query = query.where(condition)
        if when is not None:
            query = _between(query, when, start, end)
        return {(("Unassigned Pool" if k is None else names.get(k, f"User {k}")) if column.key == "owner_id" else k): n
                for k, n in db.execute(query.group_by(column)).all()}

    lead_count = lambda *where, when=None: count(  # noqa: E731
        _between(_scope(select(func.count()).select_from(Lead), Lead, owner_id).where(*where), when, start, end)
        if when is not None else _scope(select(func.count()).select_from(Lead), Lead, owner_id).where(*where))

    created = lead_count(when=Lead.created_at)
    converted = lead_count(Lead.converted_at.is_not(None), when=Lead.converted_at)
    leads_lost = lead_count(Lead.stage == "Lost", when=Lead.closed_at)
    unqualified = lead_count(Lead.stage == "Unqualified", when=Lead.closed_at)
    leads = {
        "created_in_period": created,
        "converted_in_period": converted,
        "lost_in_period": leads_lost,
        "unqualified_in_period": unqualified,
        "conversion_rate_pct": _rate(converted, converted + leads_lost + unqualified),
        "created_by_source": by(Lead.source, Lead, when=Lead.created_at),
        "created_by_owner": by(Lead.owner_id, Lead, when=Lead.created_at),
        "open_now_total": lead_count(Lead.stage.in_(LEAD_OPEN_STAGES)),
        "open_now_by_stage": {s: n for s, n in by(Lead.stage, Lead, [Lead.stage.in_(LEAD_OPEN_STAGES)]).items()},
        "all_by_stage": {s: by(Lead.stage, Lead).get(s, 0) for s in LEAD_STAGES},
        "demos_scheduled_ahead": lead_count(Lead.stage == "Demo", Lead.demo_date >= datetime.now()),
    }

    def opp_sum(column, *where, when=None):
        query = _scope(select(func.count(), func.coalesce(func.sum(column), 0)).select_from(Opportunity),
                       Opportunity, owner_id).where(*where)
        if when is not None:
            query = _between(query, when, start, end)
        n, total = db.execute(query).one()
        return n or 0, _money(total)

    won_n, won_value = opp_sum(func.coalesce(Opportunity.final_value, Opportunity.expected_value),
                               Opportunity.stage == "Won", when=Opportunity.closed_at)
    lost_n, lost_value = opp_sum(Opportunity.expected_value, Opportunity.stage == "Lost", when=Opportunity.closed_at)
    new_n, new_value = opp_sum(Opportunity.expected_value, when=Opportunity.created_at)
    open_n, open_value = opp_sum(Opportunity.expected_value, Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES))
    open_by_stage = {}
    for stage in OPPORTUNITY_OPEN_STAGES:
        n, value = opp_sum(Opportunity.expected_value, Opportunity.stage == stage)
        open_by_stage[stage] = {"count": n, "value": value}
    won_by_owner = {}
    query = _between(_scope(select(Opportunity.owner_id, func.count(),
                                   func.coalesce(func.sum(func.coalesce(Opportunity.final_value, Opportunity.expected_value)), 0))
                            .where(Opportunity.stage == "Won"), Opportunity, owner_id), Opportunity.closed_at, start, end)
    for uid, n, value in db.execute(query.group_by(Opportunity.owner_id)).all():
        won_by_owner[names.get(uid, f"User {uid}")] = {"count": n, "value": _money(value)}
    lost_reasons = by(Opportunity.lost_reason, Opportunity, [Opportunity.stage == "Lost"], when=Opportunity.closed_at)
    top_open = db.execute(_scope(select(Opportunity.name, Opportunity.stage, Opportunity.expected_value,
                                        Opportunity.expected_close_date, Opportunity.owner_id)
                                 .where(Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES),
                                        Opportunity.expected_value.is_not(None)), Opportunity, owner_id)
                          .order_by(Opportunity.expected_value.desc()).limit(5)).all()
    closing_soon = count(_scope(select(func.count()).select_from(Opportunity), Opportunity, owner_id).where(
        Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES), Opportunity.expected_close_date >= date.today(),
        Opportunity.expected_close_date <= date.today() + timedelta(days=30)))
    opportunities = {
        "created_in_period": new_n, "created_value": new_value,
        "won_in_period": won_n, "won_value": won_value,
        "lost_in_period": lost_n, "lost_value": lost_value,
        "win_rate_pct": _rate(won_n, won_n + lost_n),
        "average_won_deal": _money(won_value / won_n) if won_n else None,
        "won_by_owner": won_by_owner,
        "lost_reasons": {k or "Not given": v for k, v in lost_reasons.items()},
        "open_now": {"count": open_n, "value": open_value, "by_stage": open_by_stage},
        "open_closing_in_next_30_days": closing_soon,
        "biggest_open_deals": [{"name": n, "stage": s, "amount": _money(v), "close_date": str(c) if c else None,
                                "owner": names.get(o)} for n, s, v, c, o in top_open],
        "all_by_stage": {s: by(Opportunity.stage, Opportunity).get(s, 0) for s in OPPORTUNITY_STAGES},
    }

    task_scope = lambda *where: _scope(select(func.count()).select_from(Task), Task, owner_id).where(*where)  # noqa: E731
    tasks = {
        "open_now": count(task_scope(Task.status == "Open")),
        "overdue_now": count(task_scope(Task.status == "Open", Task.due_date < datetime.now())),
        "due_today": count(task_scope(Task.status == "Open", Task.due_date >= datetime.combine(date.today(), time()),
                                      Task.due_date < datetime.combine(date.today() + timedelta(days=1), time()))),
        "completed_in_period": count(_between(task_scope(Task.status == "Done"), Task.completed_at, start, end)),
    }
    me = acting_user()
    # amounts are added as entered: say so when the deals use more than one currency (there are no exchange rates)
    used = sorted(set(db.scalars(_scope(select(Opportunity.currency).distinct(), Opportunity, owner_id)).all())) or ["USD"]
    currency = used[0] if len(used) == 1 else (f"mixed ({', '.join(used)}): totals add the amounts as entered, "
                                                "without converting; give the amounts per deal when this matters")
    return {
        "period": label, "from": start.date().isoformat() if start else None,
        "to": (end - timedelta(days=1)).date().isoformat() if end else (date.today().isoformat() if start else None),
        "scope": ("the whole team" if me.sees_team else "your own records") +
                 (f", owner {names.get(owner_id)}" if owner_id is not None else ""),
        "currency": currency, "leads": leads, "opportunities": opportunities, "tasks": tasks,
        "assignments": "Not in this report: leads assigned from the Unassigned Pool are counted by assignment_report (created_in_period counts leads created, not assigned).",
    }


# ---------- leads assigned from the Unassigned Pool (issue 6) ----------
# What counts: one assignment = one Transfer History row (lead_transfers) with no previous owner. Only Assign gives a
# pooled lead its first owner (routers/leads.py assign_from_pool: Assign for one lead, Assign for several selected
# leads, and an approved request); a transfer between owners always has a previous owner, so it never counts here.
# The row keeps who got the lead, who assigned it and when, so later transfers or a lead going back to work don't
# change the count, and nothing is counted from the lead's creation date or from who owns it now.
# Days are IST days (the company's time zone: demo times and Home's "today" use it too). The rows are stored in
# server time without a zone (TZ, America/New_York in docker-compose.yml, which has daylight saving), so an IST day
# is turned into server time for the query, boundary by boundary.

ASSIGNMENT_ROWS = 25
ASSISTANT_NOTE = ("The AI Assistant has no action that assigns pooled leads: every assignment here was made by a "
                  "person in SalesTrack (Assign, or approving a request).")


def server_zone():
    """The time zone the timestamps are stored in: TZ (docker-compose.yml), else this computer's own."""
    try:
        return ZoneInfo(os.environ["TZ"]) if os.getenv("TZ") else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def ist_to_server(moment: datetime | None) -> datetime | None:
    """A naive IST date and time (midnight that starts a day) -> the same instant in server time, naive as stored."""
    if moment is None:
        return None
    return moment.replace(tzinfo=BUSINESS_TIMEZONE).astimezone(server_zone()).replace(tzinfo=None)


def server_to_ist(stored: datetime) -> datetime:
    zone = server_zone()
    return (stored.replace(tzinfo=zone) if zone else stored.astimezone()).astimezone(BUSINESS_TIMEZONE)


def ist_text(moment: datetime) -> str:
    return f"{moment:%d %b %Y, %I:%M %p} {BUSINESS_TZ_NAME}"


def assignment_window(period: str | None, date_from: str | None = None, date_to: str | None = None,
                      today: date | None = None) -> tuple[datetime | None, datetime | None, dict]:
    """(start, end, window): start inclusive and end exclusive in server time (what the query compares), and the same
    window in IST for the answer. A period running up to now ("today", "this week") has no end."""
    today = today or datetime.now(BUSINESS_TIMEZONE).date()
    start, end, label = period_range(period, date_from, date_to, today=today)
    window = {
        "period": label,
        "time_zone": f"{BUSINESS_TZ_NAME} (Asia/Kolkata, UTC+05:30)",
        "from": ist_text(start.replace(tzinfo=BUSINESS_TIMEZONE)) if start else "the first recorded assignment",
        "to": f"{ist_text(end.replace(tzinfo=BUSINESS_TIMEZONE))} (not included)" if end else "now",
    }
    return ist_to_server(start), ist_to_server(end), window


def _any_user(db: Session, name: str | None) -> int | None:
    """A user named in a report question, active or not (someone may have left since): 'Sai' -> their id."""
    if not name:
        return None
    term = name.strip().lower()
    users = db.query(User).all()
    exact = [u for u in users if term in (u.full_name.lower(), u.email.lower())]
    found = exact or [u for u in users if term in u.full_name.lower() or term in u.email.lower()]
    if len(found) != 1:
        listed = ", ".join(u.full_name for u in (found or users))
        raise HTTPException(status_code=400, detail=f'No single user matches "{name}". Users: {listed}')
    return found[0].id


def assignment_report(db: Session, *, period: str | None = None, date_from: str | None = None,
                      date_to: str | None = None, assigned_to: str | None = None, assigned_by: str | None = None,
                      assigned_by_me: bool = False, today: date | None = None) -> dict:
    """Leads assigned from the Unassigned Pool in a period, from the Transfer History. Scope: everyone's assignments
    for a user who sees the team's records; otherwise only the assignments the user received or made."""
    me = acting_user()
    start, end, window = assignment_window(period, date_from, date_to, today)
    to_id = _any_user(db, assigned_to)
    by_id = me.id if assigned_by_me else _any_user(db, assigned_by)
    names = dict(db.execute(select(User.id, User.full_name)).all())

    def scoped(query):
        if not me.sees_team:
            query = query.where(or_(LeadTransfer.to_user_id == me.id, LeadTransfer.transferred_by_id == me.id))
        if start is not None:
            query = query.where(LeadTransfer.transferred_at >= start)
        if end is not None:
            query = query.where(LeadTransfer.transferred_at < end)
        return query

    query = scoped(select(LeadTransfer, Lead).join(Lead, Lead.id == LeadTransfer.lead_id)
                   .where(LeadTransfer.from_user_id.is_(None)))
    if to_id is not None:
        query = query.where(LeadTransfer.to_user_id == to_id)
    if by_id is not None:
        query = query.where(LeadTransfer.transferred_by_id == by_id)
    rows = db.execute(query.order_by(LeadTransfer.transferred_at.desc(), LeadTransfer.id.desc())).all()
    between_owners = db.scalar(scoped(select(func.count()).select_from(LeadTransfer)
                                      .where(LeadTransfer.from_user_id.is_not(None)))) or 0

    def tally(key) -> dict:
        out: dict = {}
        for move, _ in rows:
            out[key(move)] = out.get(key(move), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    person = lambda uid: names.get(uid, f"User {uid}")  # noqa: E731
    via = lambda move: "approved request" if move.request_id else "Assign (one lead or several selected)"  # noqa: E731
    return {
        "what": "Leads assigned from the Unassigned Pool to a person (Assign for one lead or several selected leads, "
                "and approved requests), one per Transfer History row. Transfers between owners aren't counted.",
        **window,
        "scope": "everyone's assignments (team access)" if me.sees_team
                 else "only assignments you received or made (you don't have team access)",
        "assigned_to": person(to_id) if to_id is not None else "anyone",
        "assigned_by": person(by_id) if by_id is not None else "anyone",
        "assignments": len(rows),
        "distinct_leads": len({move.lead_id for move, _ in rows}),
        "by_assignee": tally(lambda move: person(move.to_user_id)),
        "by_assigner": tally(lambda move: person(move.transferred_by_id)),
        "via": tally(via),
        "transfers_between_owners_not_counted": between_owners,
        "assistant_assigned": 0,
        "assistant_note": ASSISTANT_NOTE,
        "rows": [{"lead": lead.name, "company": lead.company, "assigned_to": person(move.to_user_id),
                  "assigned_by": person(move.transferred_by_id), "at": ist_text(server_to_ist(move.transferred_at)),
                  "via": via(move)} for move, lead in rows[:ASSIGNMENT_ROWS]],
        "more_rows": max(0, len(rows) - ASSIGNMENT_ROWS),
        "source": "Each lead's Transfer History. A lead deleted since then is not counted (its history is deleted "
                  "with it); nothing is estimated.",
    }


DELETED_ROWS = 25


def deleted_leads_report(db: Session, *, period: str | None = None, date_from: str | None = None,
                         date_to: str | None = None, today: date | None = None) -> dict:
    """Leads > Deleted Leads for the AI Assistant: the leads restored in a period (each restore adds a note starting
    with RESTORED_NOTE, by the person who restored it) and, for the Admin and Managers, the deleted leads still waiting
    in Deleted Leads (restorable for KEEP_DAYS days). Scope as on the screens: the Admin everyone's; a Manager their
    own, their team's and pooled leads; a Salesperson only restored leads they now own (Deleted Leads is not theirs)."""
    from app.models import DeletedLead, Note
    from app.routers.deleted_leads import KEEP_DAYS, RESTORED_NOTE, _visible
    from app.security import team_ids
    from app.services import now

    me = acting_user()
    start, end, window = assignment_window(period, date_from, date_to, today)
    if start is None:
        window["from"] = "the first recorded restore or deletion"
    names = dict(db.execute(select(User.id, User.full_name)).all())
    person = lambda uid: names.get(uid, "someone")  # noqa: E731
    manages = me.is_admin or me.role == "Manager"

    def between(query, column):
        if start is not None:
            query = query.where(column >= start)
        if end is not None:
            query = query.where(column < end)
        return query

    query = between(select(Note, Lead).join(Lead, Lead.id == Note.lead_id)
                    .where(Note.body.like(f"{RESTORED_NOTE}%")), Note.created_at)
    if not me.is_admin:
        if me.role == "Manager":
            people = team_ids(db, me.id) | {me.id}
            query = query.where(or_(Lead.owner_id.in_(people), Lead.owner_id.is_(None), Note.created_by_id.in_(people)))
        else:
            query = query.where(Lead.owner_id == me.id)
    restored = db.execute(query.order_by(Note.created_at.desc(), Note.id.desc())).all()
    out = {
        "what": "Leads restored from Leads > Deleted Leads (a restored lead goes back to the Unassigned Pool with its "
                "fields and notes, and may have been assigned since), and the deleted leads that can still be restored.",
        **window,
        "scope": "everyone's" if me.is_admin else ("your own, your team's and pooled leads" if me.role == "Manager"
                                                   else "only restored leads you now own"),
        "restored_count": len(restored),
        "restored_by": dict(sorted({person(n.created_by_id): sum(1 for m, _ in restored if m.created_by_id == n.created_by_id)
                                    for n, _ in restored}.items(), key=lambda kv: (-kv[1], kv[0]))),
        "restored": [{"lead_id": lead.id, "lead": lead.name, "company": lead.company, "stage": lead.stage,
                      "restored_by": person(note.created_by_id),
                      "restored_at": ist_text(server_to_ist(note.created_at)) if note.created_at else None,
                      "owner_now": lead.owner.full_name if lead.owner else "Unassigned Pool"}
                     for note, lead in restored[:DELETED_ROWS]],
        "more_restored": max(0, len(restored) - DELETED_ROWS),
    }
    if not manages:
        out["deleted_leads"] = "Only the Admin and Managers can see Leads > Deleted Leads."
        return out
    waiting = between(_visible(db, me).where(DeletedLead.deleted_at >= now() - timedelta(days=KEEP_DAYS)),
                      DeletedLead.deleted_at)
    rows = db.scalars(waiting.order_by(DeletedLead.deleted_at.desc(), DeletedLead.id.desc())).all()
    out.update({
        "in_deleted_leads_count": len(rows),
        "keep_days": KEEP_DAYS,
        "in_deleted_leads": [{"lead": r.name, "company": r.company, "email": r.email, "stage": r.stage,
                              "owner_when_deleted": r.owner_name or "Unassigned Pool",
                              "deleted_by": person(r.deleted_by_id),
                              "deleted_at": ist_text(server_to_ist(r.deleted_at)) if r.deleted_at else None,
                              "days_left_to_restore": max(0, KEEP_DAYS - (now().date() - r.deleted_at.date()).days)
                              if r.deleted_at else None}
                             for r in rows[:DELETED_ROWS]],
        "more_in_deleted_leads": max(0, len(rows) - DELETED_ROWS),
        "how_to_restore": "Leads > Deleted Leads: tick the leads and select Restore (the Admin or a Manager). "
                          "The Assistant can't restore leads.",
    })
    return out
