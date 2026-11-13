"""Home page API: everything the dashboard needs.

- summary, pipeline, todays_tasks, won_vs_lost: same as the SQL views in database/home-page-views.sql
- seller_home (GET /api/home): the Salesperson's cards, also a Manager's Me view. Action Needed and Scheduled Demos are
  always the user's own work, today and in the next 7 days. Overall Value, Follow-up Radar and My Scorecard count the
  records in the selected period (default: the past 7 days); Recent Activity (the records changed last) is about now.
  The Admin's Follow-up Radar comes from here too (every record).
- GET /api/home/team-charts: the team cards (a Manager's team, or for the Admin every record): Overall Value,
  Win/Loss Analysis and Team Performance, and for the Admin also Lead Sources, Closing Soon and Recent Activity.
Pass owner_id to /home to see only one salesperson's records ("owned by me"); leave it out for everything you can see.
Which cards a role sees is set by the Admin on the Permissions page ("Home dashboard" permissions, app/security.py).
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.constants import LEAD_OPEN_STAGES, LEAD_STAGES, OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES
from app.database import get_db
from app.security import acting_user, team_ids
from app.models import Account, Contact, Lead, Opportunity, Task, User
from app.serializers import task_out
from app.services import ACTIVITIES, BUSINESS_TIMEZONE, activity_condition, demo_instant, now

router = APIRouter(prefix="/api", tags=["Home"])

PIPELINE = [
    *((stage, "leads") for stage in LEAD_OPEN_STAGES),
    *((stage, "opportunities") for stage in OPPORTUNITY_OPEN_STAGES),
    ("Won", "closed deals"), ("Lost", "closed deals"),
]


UPCOMING_DAYS = 7        # the Upcoming sections: from tomorrow through the next 7 days
DEFAULT_PERIOD_DAYS = 7  # the period when none is given ("Past 1 week")
CLOSING_SOON_DAYS = 30   # Closing Soon: open opportunities closing in the next 30 days (or already late)
RECENT_LIMIT = 6         # Recent Activity: the records changed last


def period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime | None]:
    """The dashboard's period [start, end) in server time. No end = up to now ("Past 1 week");
    no start = 7 days before the end. Records are stamped by the database's clock, so "up to now" has no upper bound
    rather than now() (which could leave out a record created a moment ago)."""
    def local(value) -> datetime | None:  # also when called from Python (the Assistant): not a datetime = not given
        if not isinstance(value, datetime):
            return None
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value

    end = local(end)
    start = local(start) or (end or now()) - timedelta(days=DEFAULT_PERIOD_DAYS)
    if end and start >= end:
        raise HTTPException(status_code=400, detail="The period's start must be before its end")
    return start, end


def between(column, start: datetime, end: datetime | None) -> tuple:
    """WHERE conditions: start <= column < end (no end: up to now)."""
    return (column >= start,) if end is None else (column >= start, column < end)


START = Query(None, description="Period start (ISO date/time); default: 7 days before end")
END = Query(None, description="Period end, not included (ISO date/time); default: none (up to now)")


# ---------- the cards' numbers, for any set of owners ----------
# owners(model) gives the WHERE conditions for whose records count: () for everyone, or owner_id = / IN (...)

def owned_by(ids):
    """owners() for one user id, a set of ids, or None (everyone)."""
    if ids is None:
        return lambda model: ()
    if isinstance(ids, int):
        return lambda model: (model.owner_id == ids,)
    ids = list(ids)
    return lambda model: (model.owner_id.in_(ids),)


def per_currency(rows) -> dict:
    """(currency, total) rows -> {currency: total}: amounts in different currencies are never added."""
    out: dict[str, float] = {}
    for currency, value in rows:
        if value is not None:
            out[currency] = out.get(currency, 0) + float(value)
    return out


def pipeline_card(db: Session, owners, start, end) -> dict:
    """Overall Value: opportunities created in the period by their stage now. Open and lost use the
    expected value, won the final value. Totals per currency (printed) and as plain numbers (size the ring)."""
    rows = db.execute(select(Opportunity.stage, Opportunity.currency, func.sum(Opportunity.expected_value),
                             func.sum(Opportunity.final_value))
                      .where(*owners(Opportunity), *between(Opportunity.created_at, start, end))
                      .group_by(Opportunity.stage, Opportunity.currency)).all()

    def values(stages, won=False) -> dict:
        return per_currency((cur, final if won else expected) for stage, cur, expected, final in rows if stage in stages)

    open_by, won_by, lost_by = values(OPPORTUNITY_OPEN_STAGES), values(("Won",), won=True), values(("Lost",))
    open_total, won_total, lost_total = sum(open_by.values()), sum(won_by.values()), sum(lost_by.values())
    return {
        "total_pipeline": open_total + won_total,
        "open": open_total,
        "won": won_total,
        "lost": lost_total,
        "by_currency": {
            "total_pipeline": {c: open_by.get(c, 0) + won_by.get(c, 0) for c in {*open_by, *won_by}},
            "open": open_by, "won": won_by, "lost": lost_by,
        },
    }


def win_loss(db: Session, owners, start, end) -> dict:
    """Opportunities won or lost in the period (by when they closed), the win rate and the top 3 lost reasons
    (My Scorecard, Win/Loss Analysis)."""
    value = func.coalesce(Opportunity.final_value, Opportunity.expected_value)
    rows = db.execute(select(Opportunity.stage, Opportunity.currency, func.count(), func.sum(value))
                      .where(Opportunity.stage.in_(("Won", "Lost")), *owners(Opportunity),
                             *between(Opportunity.closed_at, start, end))
                      .group_by(Opportunity.stage, Opportunity.currency)).all()

    def outcome(stage) -> dict:
        mine = [r for r in rows if r[0] == stage]
        return {"count": sum(r[2] for r in mine), "values": per_currency((r[1], r[3]) for r in mine),
                "counts": {r[1]: r[2] for r in mine}}

    won, lost = outcome("Won"), outcome("Lost")
    reason = func.coalesce(Opportunity.lost_reason, "Not given")
    reasons = db.execute(select(reason, func.count())
                         .where(Opportunity.stage == "Lost", *owners(Opportunity), *between(Opportunity.closed_at, start, end))
                         .group_by(reason).order_by(func.count().desc(), reason).limit(3)).all()
    closed = won["count"] + lost["count"]
    return {"won": won, "lost": lost, "win_rate": round(won["count"] * 100 / closed) if closed else None,
            "lost_reasons": [{"reason": r, "count": n} for r, n in reasons]}


def closing_soon(db: Session, owners) -> list[dict]:
    """Closing Soon (Admin): open opportunities closing in the next 30 days or already past their close date, soonest first."""
    rows = db.scalars(select(Opportunity).options(joinedload(Opportunity.account), joinedload(Opportunity.owner))
                      .where(*owners(Opportunity), Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES),
                             Opportunity.expected_close_date.is_not(None),
                             Opportunity.expected_close_date <= date.today() + timedelta(days=CLOSING_SOON_DAYS))
                      .order_by(Opportunity.expected_close_date, Opportunity.id).limit(6)).all()
    return [{"id": o.id, "name": o.name, "account_name": o.account.name if o.account else None, "stage": o.stage,
             "amount": float(o.expected_value) if o.expected_value is not None else None, "currency": o.currency,
             "close_date": o.expected_close_date, "late": o.expected_close_date < date.today(),
             "owner_name": o.owner.full_name if o.owner else None} for o in rows]


def recent_records(db: Session, owners) -> list[dict]:
    """Recent Activity: the leads, opportunities, accounts and contacts changed last, newest first."""
    recent = []
    for model, kind in ((Lead, "Lead"), (Opportunity, "Opportunity"), (Account, "Account"), (Contact, "Contact")):
        query = (select(model).options(joinedload(model.owner)).where(*owners(model))
                 .order_by(model.updated_at.desc(), model.id.desc()).limit(RECENT_LIMIT))
        recent += [{"type": kind, "id": r.id, "name": r.full_name if kind == "Contact" else r.name,
                    "updated_at": r.updated_at, "owner_name": r.owner.full_name if r.owner else None}
                   for r in db.scalars(query)]
    recent.sort(key=lambda r: (r["updated_at"] or datetime.min, r["id"]), reverse=True)
    return recent[:RECENT_LIMIT]


# ---------- GET /api/home: the user's own cards ----------

@router.get("/home")
def home_page(owner_id: int | None = Query(None, description="Only this salesperson's records"),
              start: datetime | None = START, end: datetime | None = END, db: Session = Depends(get_db)):
    me = acting_user()
    start, end = period(start, end)
    if not me.can("view_team_dashboard"):
        owner_id = me.id  # without the team dashboard, Home shows only your own records
    owners = owned_by(owner_id)

    def owned(query, model):
        return query.where(*owners(model))

    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery())) or 0

    def total(column, model, *conditions) -> float:
        query = owned(select(func.coalesce(func.sum(column), 0)).where(*conditions), model)
        return float(db.scalar(query) or 0)

    lead_count = dict(db.execute(owned(select(Lead.stage, func.count()), Lead).group_by(Lead.stage)).all())
    opp_count = dict(db.execute(owned(select(Opportunity.stage, func.count()), Opportunity).group_by(Opportunity.stage)).all())
    lead_count = {s: lead_count.get(s, 0) for s in LEAD_STAGES}
    opp_count = {s: opp_count.get(s, 0) for s in OPPORTUNITY_STAGES}

    tomorrow = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
    upcoming_end = tomorrow + timedelta(days=UPCOMING_DAYS)

    def tasks_due(query):  # open tasks, overdue first
        rows = db.scalars(query.where(Task.status == "Open").order_by(Task.due_date)).all()
        return sorted((task_out(t) for t in rows), key=lambda t: (not t.is_overdue, t.due_date))

    # today's tasks (open, due today or overdue), like v_todays_tasks
    todays_tasks = tasks_due(owned(select(Task), Task).where(Task.due_date < tomorrow))

    # ----- Action Needed and Scheduled Demos: always the user's own work, today and the next 7 days -----
    my_tasks = select(Task).where(Task.owner_id == me.id)
    my_today = tasks_due(my_tasks.where(Task.due_date < tomorrow))
    my_upcoming = tasks_due(my_tasks.where(Task.due_date >= tomorrow, Task.due_date < upcoming_end))

    # demos are booked in IST (stored in server time): today in IST, and the next 7 days
    ist_today = datetime.now(BUSINESS_TIMEZONE).date()
    ist_day = [datetime.combine(ist_today + timedelta(days=n), datetime.min.time(), BUSINESS_TIMEZONE)
               .astimezone().replace(tzinfo=None) for n in (0, 1, 1 + UPCOMING_DAYS)]

    def demos_between(first, last):
        return db.scalars(select(Lead).where(Lead.owner_id == me.id, Lead.demo_date >= first, Lead.demo_date < last)
                          .order_by(Lead.demo_date)).all()

    def event(lead: Lead) -> dict:
        return {"type": "Demo", "lead_id": lead.id, "name": lead.name, "company": lead.company, "start": lead.demo_date,
                "start_at": demo_instant(lead.demo_date)}

    # ----- Follow-up Radar: leads, accounts and contacts created in the period, by activity -----
    # (the same rule the lists use when a pill is clicked: services.activity_condition)
    def activity_split(model) -> dict:
        query = owned(select(model), model).where(*between(model.created_at, start, end))
        return {"total": count(query), **{f"{a}_activity" if a != "none" else "no_activity":
                                          count(query.where(activity_condition(model, a))) for a in ACTIVITIES}}

    # ----- My Scorecard: converted leads and won / lost opportunities in the period -----
    results = win_loss(db, owners, start, end)
    won, lost = results["won"], results["lost"]
    converted = db.scalar(select(func.count()).select_from(Lead)
                          .where(*owners(Lead), Lead.stage == "Converted", *between(Lead.converted_at, start, end))) or 0

    won_amount = total(Opportunity.final_value, Opportunity, Opportunity.stage == "Won")
    lost_amount = total(Opportunity.expected_value, Opportunity, Opportunity.stage == "Lost")
    return {
        "summary": {
            "total_leads": sum(lead_count.values()),
            "open_opportunities": sum(opp_count[s] for s in OPPORTUNITY_OPEN_STAGES),
            "won_deals": opp_count["Won"],
            "tasks_due_today": sum(1 for t in todays_tasks if not t.is_overdue),
        },
        "pipeline": [
            {
                "stage": stage,
                "unit": unit,
                "total": (lead_count["Lost"] + opp_count["Lost"]) if stage == "Lost"
                else lead_count.get(stage, opp_count.get(stage, 0)),
            }
            for stage, unit in PIPELINE
        ],
        "todays_tasks": todays_tasks,
        "won_vs_lost": [
            {"outcome": "Won", "deals": opp_count["Won"], "value": won_amount},
            {"outcome": "Lost", "deals": lead_count["Lost"] + opp_count["Lost"], "value": lost_amount},
        ],
        "seller_home": {
            "period": {"start": start, "end": end},  # end None: up to now
            # Action Needed and Scheduled Demos (always the user's own)
            "my_tasks": {"today": my_today, "upcoming": my_upcoming},
            "todays_events": [event(lead) for lead in demos_between(ist_day[0], ist_day[1])],
            "upcoming_events": [event(lead) for lead in demos_between(ist_day[1], ist_day[2])],
            "close_deals": pipeline_card(db, owners, start, end),  # the Overall Value card
            "recent_records": recent_records(db, owners),
            # Follow-up Radar
            "build_pipeline": activity_split(Lead),
            "accounts": activity_split(Account),
            "contacts": activity_split(Contact),
            "scorecard": {
                "converted": converted,
                "won": won["count"],
                "won_values": won["values"],
                "lost": lost["count"],
                "lost_values": lost["values"],
                "win_rate": results["win_rate"],
                "average_deal": {c: v / won["counts"][c] for c, v in won["values"].items() if won["counts"].get(c)},
            },
        },
    }


# ---------- GET /api/home/team-charts: the team cards ----------

@router.get("/home/team-charts")
def team_charts(start: datetime | None = START, end: datetime | None = END, db: Session = Depends(get_db)):
    """The team cards for the selected period. A Manager with a team sees their team (themselves and the Salespeople
    who report to them); a Manager without a team yet sees everyone. The Admin sees every record and also gets
    Lead Sources, Closing Soon and Recent Activity."""
    me = acting_user()
    start, end = period(start, end)
    if not me.can("view_team_dashboard"):
        raise HTTPException(status_code=403, detail="You don't have the \"View team dashboard\" permission")
    admin = me.role == "Admin"
    lead_of = db.get(User, me.id) if me.role == "Manager" else None
    members = team_ids(db, lead_of.id) if lead_of else set()
    scope = "team" if members else "all"
    if scope == "team":
        members.add(lead_of.id)
        people = db.scalars(select(User).where(User.id.in_(members)).order_by(User.full_name)).all()
    else:
        people = db.scalars(select(User).where(User.is_active.is_(True), User.role != "Admin").order_by(User.full_name)).all()
    ids = [p.id for p in people]
    owners = owned_by(ids if scope == "team" else None)
    of_people = owned_by(ids)

    def per_person(query) -> dict:
        return dict(db.execute(query).all())

    def per_person_currency(query) -> dict:
        out: dict = {}
        for key, currency, value in db.execute(query).all():
            out.setdefault(key, {})[currency] = float(value or 0)
        return out

    closed_value = func.coalesce(Opportunity.final_value, Opportunity.expected_value)
    created_opp, closed_opp = between(Opportunity.created_at, start, end), between(Opportunity.closed_at, start, end)
    open_opp, won_opp = Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES), Opportunity.stage == "Won"

    # ----- Team Performance -----
    open_leads = per_person(select(Lead.owner_id, func.count()).where(*of_people(Lead), Lead.stage.in_(LEAD_OPEN_STAGES),
                                                                     *between(Lead.created_at, start, end)).group_by(Lead.owner_id))
    converted = per_person(select(Lead.owner_id, func.count()).where(*of_people(Lead), Lead.stage == "Converted",
                                                                    *between(Lead.converted_at, start, end)).group_by(Lead.owner_id))
    open_value = per_person(select(Opportunity.owner_id, func.sum(Opportunity.expected_value))
                            .where(*of_people(Opportunity), open_opp, *created_opp).group_by(Opportunity.owner_id))
    won_count = per_person(select(Opportunity.owner_id, func.count())
                           .where(*of_people(Opportunity), won_opp, *closed_opp).group_by(Opportunity.owner_id))
    won = per_person(select(Opportunity.owner_id, func.sum(closed_value))
                     .where(*of_people(Opportunity), won_opp, *closed_opp).group_by(Opportunity.owner_id))
    open_cur = per_person_currency(select(Opportunity.owner_id, Opportunity.currency, func.sum(Opportunity.expected_value))
                                   .where(*of_people(Opportunity), open_opp, *created_opp)
                                   .group_by(Opportunity.owner_id, Opportunity.currency))
    won_cur = per_person_currency(select(Opportunity.owner_id, Opportunity.currency, func.sum(closed_value))
                                  .where(*of_people(Opportunity), won_opp, *closed_opp)
                                  .group_by(Opportunity.owner_id, Opportunity.currency))

    out = {
        "scope": scope,
        "team_of": {"id": lead_of.id, "name": lead_of.full_name} if scope == "team" else None,
        "period": {"start": start, "end": end},
        "pipeline": pipeline_card(db, owners, start, end),
        "win_loss": win_loss(db, owners, start, end),
        "people": [{"id": p.id, "name": p.full_name, "role": p.role, "open_leads": open_leads.get(p.id, 0),
                    "converted_this_month": converted.get(p.id, 0), "open_pipeline": float(open_value.get(p.id) or 0),
                    "won_count": won_count.get(p.id, 0), "won_this_month": float(won.get(p.id) or 0),
                    "open_pipeline_values": open_cur.get(p.id, {}), "won_this_month_values": won_cur.get(p.id, {})}
                   for p in people],
    }
    if admin:
        out["recent_records"] = recent_records(db, owners)
        out["closing_soon"] = closing_soon(db, owners)
        # Lead Sources: leads created in the period, and how many of them were converted
        sources = db.execute(select(Lead.source, func.count(), func.count().filter(Lead.stage == "Converted"))
                             .where(*owners(Lead), *between(Lead.created_at, start, end))
                             .group_by(Lead.source).order_by(func.count().desc(), Lead.source)).all()
        out["lead_sources"] = [{"source": s, "leads": n, "converted": c,
                                "conversion_rate": round(c * 100 / n) if n else None} for s, n, c in sources]
    return out

