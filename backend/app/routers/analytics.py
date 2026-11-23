"""Home > Analytics: each user builds their own board of charts to show their work up the line.

- A Salesperson's charts count their own records; a Manager's count their team's (themselves and the people who
  report to them); the Admin's count everyone's.
- Who sees a board, live: its owner, the owner's Manager (Reports To) and the Admin. So Salespeople show their work
  to their Manager, and Managers (with their team's totals) show theirs to the Admin.
- A chart is built by the user: a metric (what to count or add up), a grouping (how to split it) and a chart type.
  The numbers are worked out when the board is opened, so it is always up to date. Active leads and open
  opportunities are counted as they are now (by stage, source...); everything else in the board's period.
- Board filters (like a Salesforce dashboard): the Period (Past 1 week, Past 1 month or a custom range of local
  date-times, the Dashboard's picker) for every chart, and a click on a bar, slice or point (its point's key: a stage, source, person or dates) filters
  the other charts. The clicked chart keeps all its bars. A chart that can't take a
  filter (a lead source on an opportunity chart) says so (not_filtered_by).
- Each chart takes a quarter, half or the full width of the board's row.
- Downloads: the board as Excel (one sheet per chart) or one chart as Excel (GET .../excel).
- Send Report (the board, shown as charts) and Share as Excel (one chart): a dated snapshot with a note goes to the
  people the sender picks: any Manager or Admin (reports go to Managers and Admins only), with the sender's own
  Manager and the Admins ticked at first. Each one is notified with a link that opens it, and can mark it
  Reviewed with an optional comment and download it.
"""
import io
import json
import re
from collections import OrderedDict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.constants import (CURRENCIES, LEAD_OPEN_STAGES, LEAD_SOURCES, LEAD_STAGES, LOST_REASONS,
                           OPPORTUNITY_OPEN_STAGES, OPPORTUNITY_STAGES)
from app.database import get_db
from app.models import Lead, Opportunity, AnalyticsChart, AnalyticsReport, Task, User
from app.security import acting_user, require, team_ids
from app.services import log_activity, notify, now

def analytics_allowed() -> None:
    """Home > Analytics needs its permission (Manage Access > Permissions > Home > Analytics)."""
    require("home_analytics")


router = APIRouter(prefix="/api/analytics", tags=["Analytics"], dependencies=[Depends(analytics_allowed)])

MAX_CHARTS = 12          # charts on one board
WIDTHS = ("quarter", "half", "full")  # how much of the board's row a chart takes
DAY_GROUP_MAX_DAYS = 92  # "by day" only for periods up to about 3 months
CUSTOM_MAX_DAYS = 3 * 366

# ---------- what a chart can show ----------

TIME_GROUPS = ("day", "week", "month")
GROUPS = OrderedDict([
    ("none", "Total only"), ("stage", "Stage"), ("source", "Lead source"), ("industry", "Industry"),
    ("lost_reason", "Lost reason"), ("priority", "Priority"), ("person", "Person"),
    ("day", "Day"), ("week", "Week"), ("month", "Month"),
])
TIME = TIME_GROUPS + ("person", "none")

# key: (label, unit, groups). unit: count, money (in the chart's currency) or percent
METRICS = OrderedDict([
    ("active_leads", ("Active leads", "count", ("none", "stage", "source", "industry", "person"))),
    ("leads_created", ("Leads created", "count", ("none", "stage", "source", "industry", "person") + TIME_GROUPS)),
    ("leads_converted", ("Leads converted", "count", ("none", "source", "industry", "person") + TIME_GROUPS)),
    ("leads_lost", ("Leads lost", "count", ("none", "lost_reason", "source", "person") + TIME_GROUPS)),
    ("open_opportunities", ("Open opportunities", "count", ("none", "stage", "person"))),
    ("opportunities_created", ("Opportunities created", "count", ("none", "stage", "person") + TIME_GROUPS)),
    ("pipeline_value", ("Pipeline value (expected)", "money", ("none", "stage", "person") + TIME_GROUPS)),
    ("deals_won", ("Deals won", "count", TIME)),
    ("revenue_won", ("Revenue won", "money", TIME)),
    ("deals_lost", ("Deals lost", "count", ("none", "lost_reason", "person") + TIME_GROUPS)),
    ("win_rate", ("Win rate", "percent", ("none", "person", "week", "month"))),
    ("tasks_completed", ("Tasks completed", "count", ("none", "priority", "person") + TIME_GROUPS)),
])
CURRENT = ("active_leads", "open_opportunities")  # counted as they are now, not in a period
CHART_TYPES = OrderedDict([("column", "Column"), ("bar", "Bar"), ("line", "Line"), ("donut", "Donut"),
                           ("number", "Number")])
PERIODS = OrderedDict([("7d", "Past 1 week"), ("30d", "Past 1 month"), ("custom", "Custom range")])  # as the Dashboard's
DEFAULT_PERIOD = "7d"
# periods older charts and links may have (still worked out, no longer offered)
OLD_PERIODS = {"6m": "Past 6 months", "12m": "Past 1 year", "90d": "Past 90 days",
               "this_month": "This month", "this_quarter": "This quarter", "this_year": "This year"}
STARTER_CHARTS = [  # "Add suggested charts" on an empty board
    {"title": "Active leads", "metric": "active_leads", "group_by": "none", "chart_type": "number"},
    {"title": "Win rate", "metric": "win_rate", "group_by": "none", "chart_type": "number"},
    {"title": "Leads by stage", "metric": "leads_created", "group_by": "stage", "chart_type": "donut"},
    {"title": "Opportunities by stage", "metric": "opportunities_created", "group_by": "stage", "chart_type": "donut"},
    {"title": "Leads created", "metric": "leads_created", "group_by": "week", "chart_type": "column"},
    {"title": "Revenue won", "metric": "revenue_won", "group_by": "month", "chart_type": "line"},
]


def chart_problem(metric: str, group_by: str, chart_type: str) -> str:
    """"" when this combination can be drawn, otherwise why not (the builder shows the same rules)."""
    if metric not in METRICS:
        return "Choose what to show."
    if group_by not in METRICS[metric][2]:
        return f"{METRICS[metric][0]} can't be split by {GROUPS.get(group_by, group_by).lower()}."
    if chart_type == "number" and group_by != "none":
        return "A Number chart shows one total: choose Total only."
    if chart_type != "number" and group_by == "none":
        return "Choose how to split the chart, or use the Number chart for one total."
    if chart_type == "line" and group_by not in TIME_GROUPS:
        return "A Line chart shows a trend: split it by day, week or month."
    if chart_type == "donut" and (group_by in TIME_GROUPS or METRICS[metric][1] == "percent"):
        return "A Donut chart shows parts of a whole: split it by stage, source, person..., not by time or a rate."
    return ""


class ChartIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    metric: str
    group_by: str
    chart_type: str
    period: str = DEFAULT_PERIOD  # used when no board Period is given (the board always sends one)
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "USD"
    width: str | None = None  # quarter, half or full (of the board's row); default: by chart type

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = " ".join(v.split())
        if not v or not any(ch.isalnum() for ch in v):
            raise ValueError("Give the chart a title.")
        return v

    @model_validator(mode="after")
    def _combination(self):
        if self.period not in PERIODS and self.period not in OLD_PERIODS:
            raise ValueError("Choose a period.")
        if self.chart_type not in CHART_TYPES:
            raise ValueError("Choose a chart type.")
        if self.currency not in CURRENCIES:
            raise ValueError("Choose a currency.")
        if self.width is None:
            self.width = default_width(self.chart_type)
        if self.width not in WIDTHS:
            raise ValueError("Choose a width.")
        problem = chart_problem(self.metric, self.group_by, self.chart_type)
        if problem:
            raise ValueError(problem)
        if self.period == "custom":
            if not self.start_date or not self.end_date:
                raise ValueError("A custom range needs a start and an end date.")
            if self.end_date < self.start_date:
                raise ValueError("The end date must be on or after the start date.")
            if (self.end_date - self.start_date).days > CUSTOM_MAX_DAYS:
                raise ValueError("Choose a range of up to 3 years.")
        else:
            self.start_date = self.end_date = None
        return self


class OrderIn(BaseModel):
    ids: list[int] = Field(..., max_length=MAX_CHARTS)


class ReportIn(BaseModel):
    title: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=4000)
    recipient_ids: list[int] | None = Field(None, max_length=200)  # default: the sender's Manager and the Admins
    chart_id: int | None = None  # Share as Excel: just this chart of my board
    filters: dict = Field(default_factory=dict)  # the board's filters when it was sent (Period...)


class ReviewIn(BaseModel):
    comment: str | None = Field(None, max_length=1000)


# ---------- whose board, and who sees it ----------

def board_owners(db: Session, user: User):
    """Whose records a user's charts count: None (everyone) for the Admin, the team for a Manager, else just them."""
    if user.role == "Admin":
        return None
    if user.role == "Manager":
        return {user.id} | team_ids(db, user.id)
    return {user.id}


def scope_label(db: Session, user: User) -> str:
    if user.role == "Admin":
        return "Everyone's records"
    if user.role == "Manager":
        size = len(team_ids(db, user.id))
        return f"{user.full_name}'s team ({size + 1} {'person' if size == 0 else 'people'})"
    return f"{user.full_name}'s records"


def can_see_board(me, owner: User) -> bool:
    """Its owner, the owner's Manager (Reports To) and the Admin."""
    return me.id == owner.id or me.is_admin or owner.reports_to_id == me.id


def recipient_choices(db: Session, author: User) -> list[User]:
    """Who the author can send a report to: every active Manager and Admin but themselves (reports go to Managers and
    Admins only; Salespeople send them). Their own Manager (Reports To) comes first, then the Admins, then the other
    Managers; reviewers() says who is ticked at first."""
    users = db.scalars(select(User).where(User.is_active.is_(True), User.id != author.id,
                                          User.role.in_(["Admin", "Manager"]))).all()
    return sorted(users, key=lambda u: (u.id != author.reports_to_id, u.role != "Admin", u.full_name.lower()))


def reviewers(db: Session, author: User) -> list[User]:
    """Who a report goes to by default: the author's Manager (Reports To, if active) and every active Admin; for the
    Admin: no one (they pick)."""
    if author.role == "Admin":
        return []
    people = {}
    if author.reports_to_id:
        manager = db.get(User, author.reports_to_id)
        if manager is not None and manager.is_active:
            people[manager.id] = manager
    for admin in db.scalars(select(User).where(User.role == "Admin", User.is_active.is_(True))):
        people[admin.id] = admin
    return list(people.values())


def board_user(db: Session, user_id: int) -> User:
    owner = db.get(User, user_id)
    if owner is None or not can_see_board(acting_user(), owner):
        raise HTTPException(status_code=404, detail="This board doesn't exist or you don't have access to it")
    return owner


# ---------- the numbers ----------

def period_range(period: str, start_date: date | None = None, end_date: date | None = None) -> tuple[datetime, datetime]:
    """[start, end) in server time."""
    today = now().date()
    tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
    if period == "custom" and start_date and end_date:
        return datetime.combine(start_date, datetime.min.time()), datetime.combine(end_date + timedelta(days=1),
                                                                                   datetime.min.time())
    if period in ("7d", "30d", "90d"):
        return tomorrow - timedelta(days=int(period[:-1])), tomorrow
    if period == "6m":  # this month and the 5 before it
        first = today.replace(day=1)
        year, month = (first.year, first.month - 5) if first.month > 5 else (first.year - 1, first.month + 7)
        return datetime(year, month, 1), tomorrow
    if period == "this_month":
        return datetime(today.year, today.month, 1), tomorrow
    if period == "this_quarter":
        return datetime(today.year, 3 * ((today.month - 1) // 3) + 1, 1), tomorrow
    if period == "this_year":
        return datetime(today.year, 1, 1), tomorrow
    first = today.replace(day=1)  # 12m: this month and the 11 before it
    year, month = (first.year, first.month - 11) if first.month > 11 else (first.year - 1, first.month + 1)
    return datetime(year, month, 1), tomorrow


def period_label(chart) -> str:
    if chart.period == "custom" and chart.start_date and chart.end_date:
        return f"{chart.start_date:%d %b %Y} – {chart.end_date:%d %b %Y}"
    return PERIODS.get(chart.period) or OLD_PERIODS.get(chart.period, chart.period)


def _bucket(when: datetime, group: str) -> date:
    day = when.date()
    if group == "week":
        return day - timedelta(days=day.weekday())  # weeks start on Monday
    if group == "month":
        return day.replace(day=1)
    return day


def _buckets(start: datetime, end: datetime, group: str) -> list[date]:
    """Every day / week / month in the period (up to today), so a trend shows its empty stretches too."""
    out, current, last = [], _bucket(start, group), min((end - timedelta(seconds=1)).date(), now().date())
    while current <= last:
        out.append(current)
        if group == "month":
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            current += timedelta(days=7 if group == "week" else 1)
    return out


def _bucket_label(day: date, group: str) -> str:
    if group == "month":
        return f"{day:%b %Y}"
    if group == "week":
        return f"Week of {day:%d %b}"
    return f"{day:%d %b}"


# ---------- board filters (Period, Owner, and what was clicked on a chart) ----------

class Filters(BaseModel):
    """Applied to every chart on the board (and Explore). A field a chart's records don't have (a lead's source on an
    opportunity chart) leaves that chart unfiltered by it, and the chart says so."""
    period: str | None = None       # the board's Period (PERIODS keys): replaces each chart's own
    start_date: datetime | None = None  # a custom Period: [start, end) local date-times (a date alone: the whole day)
    end_date: datetime | None = None
    owner_id: int | None = None     # one person in the board's scope (a click on a person's bar)
    lead_stage: str | None = None
    opportunity_stage: str | None = None
    source: str | None = None       # lead source
    industry: str | None = None
    lost_reason: str | None = None
    priority: str | None = None     # task priority
    from_date: date | None = None   # a clicked day / week / month
    to_date: date | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.period is not None and self.period not in PERIODS and self.period not in OLD_PERIODS:
            raise ValueError("Choose a period.")
        if self.period == "custom":
            if not self.start_date or not self.end_date:
                raise ValueError("A custom range needs a start and an end date.")
            if self.custom_end() <= self.start_date:
                raise ValueError("The end must be after the start.")
            if (self.end_date - self.start_date).days > CUSTOM_MAX_DAYS:
                raise ValueError("Choose a range of up to 3 years.")
        else:
            self.start_date = self.end_date = None
        if (self.from_date is None) != (self.to_date is None) or (self.from_date and self.to_date < self.from_date):
            raise ValueError("Choose a date range.")
        return self

    def custom_end(self) -> datetime:
        """The custom range's end (not included); an end at midnight (a date alone) takes in that whole day."""
        end = self.end_date
        return end + timedelta(days=1) if end.time() == datetime.min.time() else end

    def custom_label(self) -> str:
        def shown(value: datetime) -> str:
            return f"{value:%d %b %Y}" + ("" if value.time() == datetime.min.time() else f" {value:%H:%M}")
        return f"{shown(self.start_date)} – {shown(self.end_date)}"

    def active(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


NO_FILTERS = Filters()


class ExploreIn(ChartIn):
    """Explore and the builder's preview: a chart that isn't saved, with the board's filters."""
    title: str = Field("Explore", min_length=1, max_length=80)
    filters: Filters = Field(default_factory=lambda: Filters())


def board_filters(period: str | None = Query(None), start_date: datetime | None = Query(None),
                  end_date: datetime | None = Query(None), owner_id: int | None = Query(None),
                  lead_stage: str | None = Query(None, max_length=30), opportunity_stage: str | None = Query(None, max_length=30),
                  source: str | None = Query(None, max_length=30), industry: str | None = Query(None, max_length=100),
                  lost_reason: str | None = Query(None, max_length=30), priority: str | None = Query(None, max_length=10),
                  from_date: date | None = Query(None), to_date: date | None = Query(None)) -> Filters:
    """The board's filters from the query string."""
    try:
        return Filters(period=period, start_date=start_date, end_date=end_date, owner_id=owner_id, lead_stage=lead_stage, opportunity_stage=opportunity_stage,
                       source=source, industry=industry, lost_reason=lost_reason, priority=priority,
                       from_date=from_date, to_date=to_date)
    except ValidationError as err:
        raise HTTPException(status_code=422, detail=err.errors()[0]["msg"].removeprefix("Value error, "))


FIELD_FILTERS = {  # which filter each dataset's records can take, and the column it is
    "leads": {"lead_stage": Lead.stage, "source": Lead.source, "industry": Lead.industry, "lost_reason": Lead.lost_reason},
    "opportunities": {"opportunity_stage": Opportunity.stage, "lost_reason": Opportunity.lost_reason},
    "tasks": {"priority": Task.priority},
}
FILTER_LABELS = {"lead_stage": "Lead stage", "opportunity_stage": "Opportunity stage", "source": "Lead source",
                 "industry": "Industry", "lost_reason": "Lost reason", "priority": "Priority"}
# a click on a chart split by this grouping filters by this field (time and person: the dates / the owner)
GROUP_FILTER = {("leads", "stage"): "lead_stage", ("opportunities", "stage"): "opportunity_stage",
                ("leads", "source"): "source", ("leads", "industry"): "industry", ("leads", "lost_reason"): "lost_reason",
                ("opportunities", "lost_reason"): "lost_reason", ("tasks", "priority"): "priority"}


def dataset_of(metric: str) -> str:
    return "leads" if metric.startswith("leads_") or metric == "active_leads" else "tasks" if metric.startswith("tasks_") else "opportunities"


def scoped_owners(db: Session, owners, filters: Filters):
    """The board's owners narrowed to the Owner filter (one person in the board's scope)."""
    if filters.owner_id is None:
        return owners
    if owners is not None and filters.owner_id not in owners:
        raise HTTPException(status_code=400, detail="Choose someone whose records this board counts")
    return {filters.owner_id}


def window(chart, filters: Filters) -> tuple[datetime, datetime, str]:
    """The chart's [start, end) after the Period filter and a clicked date range, and its label."""
    if filters.period == "custom":
        start, end = filters.start_date, filters.custom_end()
        label = filters.custom_label()
    elif filters.period:
        start, end = period_range(filters.period)
        label = PERIODS.get(filters.period) or OLD_PERIODS[filters.period]
    else:
        start, end = period_range(chart.period, chart.start_date, chart.end_date)
        label = period_label(chart)
    last_day = (filters.end_date.date() if filters.period == "custom" else chart.end_date if not filters.period else None)
    if (filters.period or chart.period) != "custom" or (last_day and last_day >= now().date()):
        # a period up to today: records saved "now" are counted even when the database's clock is ahead of the
        # business time zone (e.g. UTC after 7 PM in New York)
        end = end + timedelta(days=1)
    if filters.from_date:
        start = max(start, datetime.combine(filters.from_date, datetime.min.time()))
        end = min(end, datetime.combine(filters.to_date + timedelta(days=1), datetime.min.time()))
        label = (f"{filters.from_date:%d %b %Y}" if filters.from_date == filters.to_date
                 else f"{filters.from_date:%d %b} – {filters.to_date:%d %b %Y}")
    return start, max(start, end), label


def _conditions(metric: str, owners, start: datetime, end: datetime, currency: str, filters: Filters):
    """(model, date column, WHERE conditions, filters applied, filters this chart can't take) for a metric."""
    data = dataset_of(metric)
    if metric == "active_leads":
        model, date_col, extra = Lead, Lead.created_at, (Lead.stage.in_(LEAD_OPEN_STAGES),)
    elif metric == "open_opportunities":
        model, date_col, extra = Opportunity, Opportunity.created_at, (Opportunity.stage.in_(OPPORTUNITY_OPEN_STAGES),)
    elif data == "leads":
        model = Lead
        date_col, extra = {"leads_created": (Lead.created_at, ()),
                           "leads_converted": (Lead.converted_at, (Lead.stage == "Converted",)),
                           "leads_lost": (Lead.closed_at, (Lead.stage == "Lost",))}[metric]
    elif data == "tasks":
        model, date_col, extra = Task, Task.completed_at, (Task.status == "Done",)
    else:
        model = Opportunity
        date_col = Opportunity.created_at if metric in ("opportunities_created", "pipeline_value") else Opportunity.closed_at
        extra = {"deals_won": (Opportunity.stage == "Won",), "revenue_won": (Opportunity.stage == "Won",),
                 "deals_lost": (Opportunity.stage == "Lost",),
                 "win_rate": (Opportunity.stage.in_(["Won", "Lost"]),)}.get(metric, ())
        if metric in ("pipeline_value", "revenue_won"):
            extra = extra + (Opportunity.currency == currency,)
    where = [*extra] if metric in CURRENT else [*extra, date_col >= start, date_col < end]
    if owners is not None:
        where.append(model.owner_id.in_(list(owners)))
    applied, skipped = [], []
    for name, value in filters.active().items():
        if name not in FILTER_LABELS:
            continue
        column = FIELD_FILTERS[data].get(name)
        if column is None:
            skipped.append(FILTER_LABELS[name])
        elif value in ("Not set", "Not given"):
            where.append(column.is_(None))
            applied.append(name)
        else:
            where.append(column == value)
            applied.append(name)
    return model, date_col, where, applied, skipped


def _rows(db: Session, metric: str, owners, start: datetime, end: datetime, currency: str, filters: Filters = NO_FILTERS):
    """(when, owner_id, group values dict, value) for each record the metric counts, and the filters skipped."""
    model, date_col, where, _, skipped = _conditions(metric, owners, start, end, currency, filters)
    out = []
    if model is Lead:
        query = select(date_col, Lead.owner_id, Lead.stage, Lead.source, Lead.industry, Lead.lost_reason).where(*where)
        for when, owner, stage, source, industry, reason in db.execute(query):
            out.append((when, owner, {"stage": stage, "source": source, "industry": industry or "Not set",
                                      "lost_reason": reason or "Not given"}, 1))
    elif model is Task:
        for when, owner, priority in db.execute(select(Task.completed_at, Task.owner_id, Task.priority).where(*where)):
            out.append((when, owner, {"priority": priority}, 1))
    else:
        query = select(date_col, Opportunity.owner_id, Opportunity.stage, Opportunity.lost_reason,
                       Opportunity.expected_value, Opportunity.final_value).where(*where)
        for when, owner, stage, reason, expected, final in db.execute(query):
            if metric == "pipeline_value":
                value = float(expected or 0)
            elif metric == "revenue_won":
                value = float(final if final is not None else expected or 0)
            elif metric == "win_rate":
                value = 1 if stage == "Won" else 0
            else:
                value = 1
            out.append((when, owner, {"stage": stage, "lost_reason": reason or "Not given"}, value))
    return out, skipped


def _bucket_end(day: date, group: str) -> date:
    if group == "month":
        return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return day + timedelta(days=6 if group == "week" else 0)


def compute(db: Session, chart, owners, filters: Filters = NO_FILTERS) -> dict:
    """The chart's numbers: points [{label, value, key}] in display order, and the total. key is what a click on the
    point filters by: the grouping's value, the person's id, or the day / week / month's dates."""
    metric, group = chart.metric, chart.group_by
    label, unit, _ = METRICS[metric]
    # the chart that was clicked keeps all its bars (the clicked one is highlighted): its own field doesn't filter it
    own = {"person": ("owner_id",), **{g: ("from_date", "to_date") for g in TIME_GROUPS}}.get(group) \
        or ((GROUP_FILTER[(dataset_of(metric), group)],) if (dataset_of(metric), group) in GROUP_FILTER else ())
    if any(getattr(filters, f) is not None for f in own):
        filters = filters.model_copy(update={f: None for f in own})
    owners = scoped_owners(db, owners, filters)
    start, end, shown_period = window(chart, filters)
    if metric in CURRENT:
        shown_period = "As of now"
    if group == "day" and (end - start).days > DAY_GROUP_MAX_DAYS:
        group = "week"  # a long period by day is unreadable: shown by week
    names = {}
    if group == "person":
        names = dict(db.execute(select(User.id, User.full_name)).all())
    sums: dict = {}
    counts: dict = {}  # win rate: closed deals per group
    rows, skipped = _rows(db, metric, owners, start, end, chart.currency, filters)
    for when, owner, values, value in rows:
        if when is None:
            continue
        if group == "none":
            key = "Total"
        elif group in TIME_GROUPS:
            key = _bucket(when, group)
        elif group == "person":
            key = owner
        else:
            key = values.get(group) or "Not set"
        sums[key] = sums.get(key, 0) + value
        counts[key] = counts.get(key, 0) + 1

    def final(key):
        if unit == "percent":
            return round(100 * sums[key] / counts[key], 1) if counts.get(key) else None
        return round(sums.get(key, 0), 2)

    empty = None if unit == "percent" else 0
    if group in TIME_GROUPS:
        points = [{"label": _bucket_label(day, group), "value": final(day) if day in sums else empty,
                   "key": {"from_date": day.isoformat(), "to_date": _bucket_end(day, group).isoformat()}}
                  for day in _buckets(start, end, group)] if end > start else []
    elif group == "none":
        points = [{"label": "Total", "value": final("Total") if "Total" in sums else empty, "key": None}]
    elif group == "person":
        keys = sorted(sums, key=lambda k: (-sums[k] if unit != "percent" else -(final(k) or 0), names.get(k, "")))
        points = [{"label": names.get(k, "Unknown"), "value": final(k), "key": {"owner_id": k}} for k in keys]
    else:
        order = {"stage": LEAD_STAGES if dataset_of(metric) == "leads" else OPPORTUNITY_STAGES, "source": LEAD_SOURCES,
                 "lost_reason": LOST_REASONS, "priority": ["High", "Normal", "Low"]}.get(group)
        keys = list(sums)
        if order:
            keys.sort(key=lambda k: (order.index(k) if k in order else len(order), str(k)))
        else:
            keys.sort(key=lambda k: (-sums[k], str(k)))
        field = GROUP_FILTER.get((dataset_of(metric), group))
        points = [{"label": str(k), "value": final(k), "key": {field: k} if field else None} for k in keys]
    if unit == "percent":
        closed = sum(counts.values())
        total = round(100 * sum(sums.values()) / closed, 1) if closed else None
    else:
        total = round(sum(sums.values()), 2)
    return {"metric_label": label, "unit": unit, "currency": chart.currency if unit == "money" else None,
            "dataset": dataset_of(metric), "group_shown": group, "period_label": shown_period, "start": start,
            "end": end, "points": points, "total": total, "not_filtered_by": skipped}


def chart_out(db: Session, chart: AnalyticsChart, owners, filters: Filters = NO_FILTERS) -> dict:
    return {"id": chart.id, "title": chart.title, "metric": chart.metric, "group_by": chart.group_by,
            "chart_type": chart.chart_type, "period": chart.period, "start_date": chart.start_date,
            "end_date": chart.end_date, "currency": chart.currency, "position": chart.position,
            "width": chart.width or default_width(chart.chart_type), **compute(db, chart, owners, filters)}


def default_width(chart_type: str) -> str:
    return "quarter" if chart_type == "number" else "half"


RECORD_LIMIT = 100


def records(db: Session, chart, owners, filters: Filters) -> dict:
    """Explore's table: the records behind a chart (newest first, up to RECORD_LIMIT), with links."""
    owners = scoped_owners(db, owners, filters)
    start, end, shown_period = window(chart, filters)
    model, date_col, where, _, skipped = _conditions(chart.metric, owners, start, end, chart.currency, filters)
    total = db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    names = dict(db.execute(select(User.id, User.full_name)).all())
    rows = []
    found = db.scalars(select(model).where(*where).order_by(date_col.desc()).limit(RECORD_LIMIT)).all()
    if model is Lead:
        columns = ["Name", "Company", "Source", "Stage", "Owner", "Date"]
        for r in found:
            rows.append({"id": r.id, "link": f"#/leads/{r.id}", "cells": [r.name, r.company, r.source, r.stage,
                                                                       names.get(r.owner_id), _date(r, date_col)]})
    elif model is Task:
        columns = ["Task", "Priority", "Owner", "Completed"]
        for r in found:
            rows.append({"id": r.id, "link": f"#/tasks?task={r.id}", "cells": [r.title, r.priority, names.get(r.owner_id),
                                                                             _date(r, date_col)]})
    else:
        columns = ["Name", "Account", "Stage", "Owner", "Amount", "Date"]
        for r in found:
            value = r.final_value if r.stage == "Won" and r.final_value is not None else r.expected_value
            rows.append({"id": r.id, "link": f"#/opportunities/{r.id}",
                         "cells": [r.name, r.account.name if r.account else None, r.stage, names.get(r.owner_id),
                                   {"money": float(value or 0), "currency": r.currency}, _date(r, date_col)]})
    return {"columns": columns, "rows": rows, "total": total, "period_label": shown_period,
            "not_filtered_by": skipped}


def _date(record, column) -> str | None:
    value = getattr(record, column.key)
    return value.isoformat() if value else None


def _ids(text: str | None) -> list[int]:
    """recipient_ids is stored as ",3,7," (so a recipient is found with LIKE '%,3,%')."""
    return [int(i) for i in (text or "").split(",") if i.strip().isdigit()]


def is_recipient(report: AnalyticsReport, me) -> bool:
    if report.recipient_ids:
        return me.id in _ids(report.recipient_ids)
    author = report.user  # older reports: the author's Manager and the Admin
    return author is not None and (me.is_admin or author.reports_to_id == me.id)


def report_out(report: AnalyticsReport, *, full: bool = False) -> dict:
    me = acting_user()
    author = report.user
    out = {"id": report.id, "kind": report.kind or "board", "title": report.title, "note": report.note,
           "created_at": report.created_at,
           "user_id": report.user_id, "user_name": author.full_name if author else None,
           "user_role": author.role if author else None, "sent_to": report.sent_to,
           "reviewed_by_name": report.reviewed_by.full_name if report.reviewed_by else None,
           "reviewed_at": report.reviewed_at, "review_comment": report.review_comment,
           "can_review": report.reviewed_at is None and author is not None and me.id != author.id
           and is_recipient(report, me)}
    if full:
        out["charts"] = json.loads(report.charts or "[]")
    else:
        out["chart_count"] = len(json.loads(report.charts or "[]"))
    return out


def my_chart(db: Session, chart_id: int) -> AnalyticsChart:
    chart = db.get(AnalyticsChart, chart_id)
    if chart is None or chart.user_id != acting_user().id:
        raise HTTPException(status_code=404, detail="This chart doesn't exist or isn't yours")
    return chart


# ---------- endpoints ----------

@router.get("/options")
def options():
    """What the chart builder offers (and which combinations work: chart_problem)."""
    return {"metrics": [{"key": k, "label": v[0], "unit": v[1], "groups": list(v[2])} for k, v in METRICS.items()],
            "groups": [{"key": k, "label": v} for k, v in GROUPS.items()],
            "chart_types": [{"key": k, "label": v} for k, v in CHART_TYPES.items()],
            "periods": [{"key": k, "label": v} for k, v in PERIODS.items()],
            "default_period": DEFAULT_PERIOD, "currencies": CURRENCIES, "max_charts": MAX_CHARTS}


@router.get("/people")
def people(db: Session = Depends(get_db)):
    """Whose boards I can open: mine first, then the people who report to me (the Admin: every Manager, then everyone
    else), with their chart count and their latest report."""
    me = acting_user()
    query = select(User).where(User.is_active.is_(True))
    if not me.is_admin:
        query = query.where(or_(User.id == me.id, User.reports_to_id == me.id))
    users = db.scalars(query).all()
    rank = {"Admin": 0, "Manager": 1}
    users.sort(key=lambda u: (u.id != me.id, rank.get(u.role, 2), u.full_name.lower()))
    charts = {}
    for user_id, in db.execute(select(AnalyticsChart.user_id)):
        charts[user_id] = charts.get(user_id, 0) + 1
    latest = {}
    for user_id, created in db.execute(select(AnalyticsReport.user_id, AnalyticsReport.created_at)
                                       .order_by(AnalyticsReport.created_at)):
        latest[user_id] = created
    return [{"id": u.id, "full_name": u.full_name, "role": u.role, "me": u.id == me.id,
             "reports_to_name": u.reports_to_name, "charts": charts.get(u.id, 0), "last_report_at": latest.get(u.id)}
            for u in users]


def scope_people(db: Session, owners) -> list[dict]:
    """The Owner filter's choices: the people a board counts (none to choose for a one-person board)."""
    query = select(User.id, User.full_name).where(User.role != "Admin")
    if owners is not None:
        if len(owners) < 2:
            return []
        query = select(User.id, User.full_name).where(User.id.in_(list(owners)))
    return [{"id": i, "full_name": n} for i, n in db.execute(query.order_by(User.full_name))]


@router.get("/boards/{user_id}")
def board(user_id: int, filters: Filters = Depends(board_filters), db: Session = Depends(get_db)):
    """A user's charts with today's numbers (after the board's filters), and their latest reports."""
    owner = board_user(db, user_id)
    owners = board_owners(db, owner)
    charts = db.scalars(select(AnalyticsChart).where(AnalyticsChart.user_id == owner.id)
                        .order_by(AnalyticsChart.position, AnalyticsChart.id)).all()
    reports = db.scalars(select(AnalyticsReport).where(AnalyticsReport.user_id == owner.id)
                         .order_by(AnalyticsReport.id.desc()).limit(10)).all()
    me = acting_user()
    return {"user": {"id": owner.id, "full_name": owner.full_name, "role": owner.role},
            "scope": scope_label(db, owner), "can_edit": owner.id == me.id,
            "can_send": owner.id == me.id and bool(recipient_choices(db, owner)),
            "people": scope_people(db, owners), "filters": filters.active(),
            "charts": [chart_out(db, c, owners, filters) for c in charts], "reports": [report_out(r) for r in reports]}


def unsaved(data: ExploreIn, user_id: int) -> AnalyticsChart:
    return AnalyticsChart(**data.model_dump(exclude={"filters"}), user_id=user_id, position=0)


@router.post("/charts/preview")
def preview(data: ExploreIn, db: Session = Depends(get_db)):
    """The builder's live preview and Explore: the chart's numbers (my board's scope) without saving it."""
    me = db.get(User, acting_user().id)
    return chart_out(db, unsaved(data, me.id), board_owners(db, me), data.filters)


@router.post("/records")
def explore_records(data: ExploreIn, db: Session = Depends(get_db)):
    """Explore's table: the records behind a chart in my board's scope, with the filters."""
    me = db.get(User, acting_user().id)
    return records(db, unsaved(data, me.id), board_owners(db, me), data.filters)


@router.post("/charts", status_code=status.HTTP_201_CREATED)
def add_chart(data: ChartIn, db: Session = Depends(get_db)):
    me = db.get(User, acting_user().id)
    existing = db.scalars(select(AnalyticsChart.position).where(AnalyticsChart.user_id == me.id)).all()
    if len(existing) >= MAX_CHARTS:
        raise HTTPException(status_code=400, detail=f"A board holds up to {MAX_CHARTS} charts. Remove one first.")
    chart = AnalyticsChart(**data.model_dump(), user_id=me.id, position=max(existing, default=-1) + 1)
    db.add(chart)
    db.commit()
    db.refresh(chart)
    return chart_out(db, chart, board_owners(db, me))


@router.post("/charts/suggested", status_code=status.HTTP_201_CREATED)
def add_suggested(db: Session = Depends(get_db)):
    """An empty board: adds a few starter charts the user can change or remove."""
    me = db.get(User, acting_user().id)
    if db.scalars(select(AnalyticsChart.id).where(AnalyticsChart.user_id == me.id)).first() is not None:
        raise HTTPException(status_code=400, detail="Your board already has charts")
    for position, spec in enumerate(STARTER_CHARTS):
        db.add(AnalyticsChart(**ChartIn(**spec).model_dump(), user_id=me.id, position=position))
    db.commit()
    return board(me.id, NO_FILTERS, db)


@router.put("/charts/{chart_id}")
def change_chart(chart_id: int, data: ChartIn, db: Session = Depends(get_db)):
    chart = my_chart(db, chart_id)
    for field, value in data.model_dump().items():
        setattr(chart, field, value)
    db.commit()
    db.refresh(chart)
    return chart_out(db, chart, board_owners(db, db.get(User, chart.user_id)))


@router.delete("/charts/{chart_id}")
def remove_chart(chart_id: int, db: Session = Depends(get_db)):
    db.delete(my_chart(db, chart_id))
    db.commit()
    return {"deleted": chart_id}


@router.put("/charts-order")
def reorder(data: OrderIn, db: Session = Depends(get_db)):
    """The board's order: the chart ids, first to last (only the user's own charts)."""
    me = acting_user()
    charts = {c.id: c for c in db.scalars(select(AnalyticsChart).where(AnalyticsChart.user_id == me.id))}
    if set(data.ids) != set(charts) or len(data.ids) != len(charts):
        raise HTTPException(status_code=400, detail="Send every chart on your board once")
    for position, chart_id in enumerate(data.ids):
        charts[chart_id].position = position
    db.commit()
    return {"ids": data.ids}


@router.get("/recipients")
def recipients(db: Session = Depends(get_db)):
    """Who I can send a report or a chart to, and who is picked at first (my Manager and the Admins)."""
    me = db.get(User, acting_user().id)
    picked = {u.id for u in reviewers(db, me)}
    return [{"id": u.id, "full_name": u.full_name, "role": u.role, "picked": u.id in picked}
            for u in recipient_choices(db, me)]


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def send_report(data: ReportIn, db: Session = Depends(get_db)):
    """Send Report (my board, shown as charts) or Share as Excel (one chart of my board): a dated snapshot with a
    note goes to the people picked (default: my Manager and the Admins). Each one is notified with a link to it."""
    me = db.get(User, acting_user().id)
    choices = {u.id: u for u in recipient_choices(db, me)}
    wanted = data.recipient_ids if data.recipient_ids is not None else [u.id for u in reviewers(db, me)]
    if any(i not in choices for i in wanted):
        raise HTTPException(status_code=400, detail="Choose people from the list to send it to.")
    to = [choices[i] for i in dict.fromkeys(wanted)]
    if not to:
        raise HTTPException(status_code=400, detail="Choose who to send it to.")
    try:
        filters = Filters(**{k: v for k, v in (data.filters or {}).items() if k in Filters.model_fields})
    except ValidationError as err:
        raise HTTPException(status_code=422, detail=err.errors()[0]["msg"].removeprefix("Value error, "))
    query = select(AnalyticsChart).where(AnalyticsChart.user_id == me.id)
    if data.chart_id is not None:
        query = query.where(AnalyticsChart.id == data.chart_id)
    charts = db.scalars(query.order_by(AnalyticsChart.position, AnalyticsChart.id)).all()
    if data.chart_id is not None and not charts:
        raise HTTPException(status_code=404, detail="This chart doesn't exist or isn't yours")
    if not charts:
        raise HTTPException(status_code=400, detail="Add at least one chart to your board before sending a report.")
    owners = board_owners(db, me)
    snapshot = [chart_out(db, c, owners, filters) | {"scope": scope_label(db, me)} for c in charts]
    kind = "chart" if data.chart_id is not None else "board"
    default_title = charts[0].title if kind == "chart" else f"{me.full_name}'s report, {now():%d %b %Y}"
    title = (data.title or "").strip() or default_title
    report = AnalyticsReport(user_id=me.id, kind=kind, title=title[:120], note=(data.note or "").strip() or None,
                             charts=json.dumps(snapshot, default=str), sent_to=", ".join(p.full_name for p in to)[:300],
                             recipient_ids="," + ",".join(str(p.id) for p in to) + ",")
    db.add(report)
    db.flush()
    what = (f'shared the chart "{report.title}" with you (Excel).' if kind == "chart" else
            f'sent you a report: "{report.title}" ({len(charts)} chart{"s" if len(charts) != 1 else ""}).')
    for person in to:
        notify(db, person.id, "Analytics chart shared" if kind == "chart" else "Analytics report received",
               f"{me.full_name} {what}" + (f"\nNote: {report.note[:300]}" if report.note else "")
               + "\nOpen it on Home > Analytics.",
               link=f"/analytics?report={report.id}", category="assignment",
               why="You get this email because it was sent to you in SalesTrack CRM.")
    log_activity(db, me.id, "Analytics chart shared" if kind == "chart" else "Analytics report sent", report.title,
                 f"To: {report.sent_to}")
    db.commit()
    db.refresh(report)
    return report_out(report, full=True)


@router.get("/reports")
def list_reports(box: str = Query("received", pattern="^(received|sent)$"), db: Session = Depends(get_db)):
    """received: reports and charts sent to me, not reviewed first. sent: mine."""
    me = acting_user()
    query = select(AnalyticsReport).join(User, User.id == AnalyticsReport.user_id)
    if box == "sent":
        query = query.where(AnalyticsReport.user_id == me.id)
    else:
        legacy = AnalyticsReport.recipient_ids.is_(None)  # older reports: to the author's Manager and the Admin
        if not me.is_admin:
            legacy = legacy & (User.reports_to_id == me.id)
        query = query.where(AnalyticsReport.user_id != me.id,
                            or_(AnalyticsReport.recipient_ids.like(f"%,{me.id},%"), legacy))
    rows = db.scalars(query.order_by(AnalyticsReport.reviewed_at.is_not(None), AnalyticsReport.id.desc()).limit(200)).all()
    return [report_out(r) for r in rows]


def visible_report(db: Session, report_id: int) -> AnalyticsReport:
    """Its author, the people it was sent to, and those who can see the author's board (their Manager, the Admin)."""
    me = acting_user()
    report = db.get(AnalyticsReport, report_id)
    if report is None or report.user is None or not (is_recipient(report, me) or can_see_board(me, report.user)):
        raise HTTPException(status_code=404, detail="This report doesn't exist or you don't have access to it")
    return report


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    return report_out(visible_report(db, report_id), full=True)


@router.post("/reports/{report_id}/review")
def review(report_id: int, data: ReviewIn, db: Session = Depends(get_db)):
    """The author's Manager or the Admin marks the report reviewed, with an optional comment (the author is told)."""
    me = acting_user()
    report = visible_report(db, report_id)
    if not report_out(report)["can_review"]:
        if report.reviewed_at is not None:
            raise HTTPException(status_code=400, detail="This report was already reviewed")
        raise HTTPException(status_code=403, detail="Only the people it was sent to can review this report")
    report.reviewed_by_id = me.id
    report.reviewed_at = now()
    report.review_comment = (data.comment or "").strip() or None
    notify(db, report.user_id, "Analytics report reviewed",
           f'{me.full_name} reviewed your report "{report.title}".'
           + (f"\nComment: {report.review_comment}" if report.review_comment else ""),
           link=f"/analytics?report={report.id}", category="assignment")
    log_activity(db, me.id, "Analytics report reviewed", report.title, f"From: {report.user.full_name}")
    db.commit()
    db.refresh(report)
    return report_out(report, full=True)


# ---------- Excel downloads: one sheet per chart ----------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cell_value(value, unit):
    if value is None:
        return None
    return value / 100 if unit == "percent" else value


def workbook(charts: list[dict], heading: str) -> bytes:
    """An .xlsx with a sheet per chart: its title, whose records and when, then each bar's label and value and the
    total (money with its currency, a rate as a percentage)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    book.remove(book.active)
    used: set[str] = set()
    groups = dict(GROUPS)
    for chart in charts:
        name = re.sub(r"[\[\]:*?/\\]", " ", chart.get("title") or "Chart").strip()[:31] or "Chart"
        base, n = name, 2
        while name.lower() in used:
            suffix = f" ({n})"
            name, n = base[:31 - len(suffix)] + suffix, n + 1
        used.add(name.lower())
        sheet = book.create_sheet(name)
        unit, currency = chart.get("unit"), chart.get("currency")
        sheet.append([chart.get("title")])
        sheet["A1"].font = Font(bold=True, size=14)
        sheet.append([heading])
        sheet.append([f"Period: {chart.get('period_label')}"])
        sheet.append([])
        group = chart.get("group_shown") or chart.get("group_by")
        value_name = chart.get("metric_label") or "Value"
        if unit == "money" and currency:
            value_name += f" ({currency})"
        sheet.append([groups.get(group, "Total") if group != "none" else "Total", value_name])
        for cell in sheet[5]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0176D3")
        number_format = "0.0%" if unit == "percent" else "#,##0.00" if unit == "money" else "#,##0"
        for point in chart.get("points") or []:
            sheet.append([point.get("label"), _cell_value(point.get("value"), unit)])
            sheet.cell(sheet.max_row, 2).number_format = number_format
        if group != "none":
            sheet.append(["Total", _cell_value(chart.get("total"), unit)])
            sheet.cell(sheet.max_row, 1).font = sheet.cell(sheet.max_row, 2).font = Font(bold=True)
            sheet.cell(sheet.max_row, 2).number_format = number_format
        for column, width in ((1, 32), (2, 22)):
            sheet.column_dimensions[get_column_letter(column)].width = width
    if not book.sheetnames:
        book.create_sheet("Board").append(["No charts"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _excel(content: bytes, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "analytics"
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"'})


def _heading(owner: User, db: Session) -> str:
    return f"{scope_label(db, owner)} • downloaded {now():%d %b %Y %H:%M}"


@router.get("/boards/{user_id}/excel")
def board_excel(user_id: int, chart_id: int | None = Query(None), filters: Filters = Depends(board_filters),
                db: Session = Depends(get_db)):
    """The board (or one chart of it: chart_id) as an Excel file, one sheet per chart, with the board's filters."""
    owner = board_user(db, user_id)
    owners = board_owners(db, owner)
    query = select(AnalyticsChart).where(AnalyticsChart.user_id == owner.id)
    if chart_id is not None:
        query = query.where(AnalyticsChart.id == chart_id)
    charts = db.scalars(query.order_by(AnalyticsChart.position, AnalyticsChart.id)).all()
    if chart_id is not None and not charts:
        raise HTTPException(status_code=404, detail="This chart doesn't exist")
    data = [chart_out(db, c, owners, filters) for c in charts]
    name = data[0]["title"] if chart_id is not None else f"{owner.full_name} analytics"
    return _excel(workbook(data, _heading(owner, db)), f"{name} {now():%Y-%m-%d}")


@router.get("/reports/{report_id}/excel")
def report_excel(report_id: int, db: Session = Depends(get_db)):
    """A sent report or shared chart as an Excel file (the numbers as they were when it was sent)."""
    report = visible_report(db, report_id)
    heading = f"Sent by {report.user.full_name} on {report.created_at:%d %b %Y}" if report.created_at else report.title
    return _excel(workbook(json.loads(report.charts or "[]"), heading), report.title)
