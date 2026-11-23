"""In stage: how long a lead has been at its current Lead Status (the Leads list's In stage column, its filter and its
sort). It is worked out from the lead's own history each time the list is asked for: nothing is saved, so a refresh
shows the time gone by without changing the lead or its Last Modified.

When the clock starts
- When the lead is first assigned to someone who was a Salesperson at that moment:
  * an assignment out of the Unassigned Pool (a lead_transfers row with no previous owner: Assign, bulk Assign or an
    approved request). The pool has only ever gone to an active Salesperson (routers/leads.py pool_recipient);
  * a lead added by hand (the New Lead form, the Assistant) for a Salesperson: when it was added (its first
    stage_history row), the owner it was added for being the one the transfers start from;
  * a transfer (lead_transfers) to a Salesperson.
  An upload is never an assignment, and a lead an Admin or a Manager owns doesn't start until a Salesperson gets it.
- A Lead Status change after that starts it again (a stage_history row to a different status; a demo reschedule,
  Demo -> Demo, isn't one). A transfer between owners doesn't, to anyone. lead.assigned_at is not used: it changes on
  every transfer.

What the history can tell (and the limits)
- Roles: a user's role is stored, not its history. Before 28 Oct 2026 a role couldn't be changed at all; since then
  every change saves users.role_changed_at, but only the latest one. So someone's role at a moment is their role now
  when no change was recorded after that moment; before their latest change it is unknown. (The Activity Log's "Role
  changed" lines are free text and aren't read.)
- Owners: older versions changed owners without a lead_transfers row (Users > Transfer records moved open leads without
  one, and at first an owner could be edited directly). When this database started recording every change isn't
  stored anywhere (no migration or deployment log), and a commit date says nothing about when a database got it. So it
  is read from the records themselves: leads.assigned_at and Unassigned Pool assignments are only ever written by
  versions that record every change of owner (they came with the pool, after both fixes), so
  * a lead added with assigned_at and never handed over since, or whose first hand-over is out of the pool, has its
    whole owner history (added by such a version);
  * otherwise, its history is complete from the earliest such record in the database (recorded_from below) on: the
    latest moment the recording version is known to have been running here. Before that, who owned the lead isn't
    known (Not recorded). That assumes the database never went back to an older version afterwards.
- An unknown step before the first Salesperson assignment we can see (a role or an owner we can't tell) means the start
  isn't known: Not recorded, never the later transfer or the creation date in its place. A status change made while a
  Salesperson is known to have had the lead is still a known start.

The other states
- "not_started": in the Unassigned Pool, or never assigned to a Salesperson (an Admin's or a Manager's own lead).
- "closed": Converted, Lost or Unqualified. Closed leads aren't timed or rated, so they never build up stalled time.
  Reopening an Unqualified lead is a status change, so its clock starts again then.
- "not_recorded": as above, or the lead has no history or its latest recorded status isn't its status now. No date is
  made up and nothing is written back.
- "timed": "since" when, and, as every open status has limits (STAGE_DAYS), "on_track", "attention" or "stalled".
No code returns a lead to the pool. If one were (owner cleared), it would show Not started, and its next assignment from
the pool would start the clock again.

Times: stage_history.changed_at, lead_transfers.transferred_at and users.role_changed_at are all stored in the server's
time zone with no zone (TZ / PGTZ in docker-compose.yml, as schemas.server_instant), so they are compared as stored.
Elapsed time is real time between two instants, from one reference time per request: the cut-offs ("2 days ago"...) are
worked out as instants and turned into stored server time, so a day across a DST change is still 24 hours. A stored time
in the repeated autumn hour is read as the first one (as server_instant does).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, null, or_, select, true, union_all
from sqlalchemy.orm import Session, aliased

from app.constants import LEAD_OPEN_STAGES
from app.models import Lead, LeadTransfer, StageHistory, User

# Lead Status: (needs attention at, stalled at), in days of elapsed time. Below the first: on track.
STAGE_DAYS = {"New": (2, 5), "Nurturing": (7, 14), "Revisit": (14, 30), "Demo": (5, 10)}
CATEGORIES = ("on_track", "attention", "stalled")
NEUTRAL_ORDER = ("not_started", "not_recorded", "closed")  # after every timed lead, in this order, either way round
SALESPERSON = "Salesperson"


def reference_time() -> datetime:
    """Now, as an instant (one per request)."""
    return datetime.now(timezone.utc)


def to_instant(stored: datetime, zone=None) -> datetime:
    """A stored server time (no zone) as an instant in UTC. zone: the server's zone (default: this process's, TZ)."""
    local = stored.replace(tzinfo=zone) if zone is not None else stored.astimezone()
    return local.astimezone(timezone.utc)


def to_stored(instant: datetime, zone=None) -> datetime:
    """An instant as stored server time (no zone)."""
    return (instant.astimezone(zone) if zone is not None else instant.astimezone()).replace(tzinfo=None)


class Clock:
    """The reference time of one response: every cut-off and every lead's elapsed time come from it."""

    def __init__(self, at: datetime | None = None, zone=None):
        self.at = (at or reference_time()).astimezone(timezone.utc)
        self.zone = zone
        # per open status: (needs attention if it started on or before, stalled if on or before), as stored
        self.cutoffs = {stage: tuple(to_stored(self.at - timedelta(days=days), zone) for days in limits)
                        for stage, limits in STAGE_DAYS.items()}

    def seconds(self, since: datetime) -> int:
        """Whole seconds from since (stored server time) to the reference time (never below 0)."""
        return max(0, int((self.at - to_instant(since, self.zone)).total_seconds()))


def earliest(*times):
    """The earliest of these times, leaving out missing ones (NULL when all are missing). Plain CASE and COALESCE, so
    SQLite and PostgreSQL agree (PostgreSQL's LEAST ignores NULLs, SQLite's MIN() of several values doesn't). Give it
    columns: each value is written out twice."""
    out = times[0]
    for value in times[1:]:
        out = case((value < out, value), else_=func.coalesce(out, value))
    return out


def step(query, name):
    """One step of the calculation as its own subquery. OFFSET 0 keeps PostgreSQL and SQLite from folding it into the
    next step, which would write every expression out again wherever the next step uses it."""
    return query.offset(0).subquery(name)


def role_known(user, at):
    """The user's role now was already theirs at `at`: no role change recorded after it (see the module notes)."""
    return or_(user.role_changed_at.is_(None), user.role_changed_at <= at)


def salesperson_at(user, at):
    return and_(user.role == SALESPERSON, role_known(user, at))


def recorded_from():
    """A one-row subquery: the earliest record only a version that records every change of owner writes (a lead's
    assigned_at, an assignment out of the Unassigned Pool). NULL when there is none yet. For the whole database, also
    when a page of leads is asked for."""
    stamps = union_all(select(Lead.assigned_at.label("at")).where(Lead.assigned_at.is_not(None)),
                       select(LeadTransfer.transferred_at.label("at")).where(LeadTransfer.from_user_id.is_(None)))
    stamps = stamps.subquery("clock_owner_stamps")
    return select(func.min(stamps.c.at).label("since")).subquery("clock_recorded_from")


def clock_rows(clock: Clock, lead_ids: list[int] | None = None):
    """A subquery with one row per lead: id, since (stored server time, only when timed), state and category.
    lead_ids: only these leads (a page); otherwise every lead (to filter or sort a whole list before paging)."""
    h, t = StageHistory, LeadTransfer
    status_change = and_(h.from_stage.is_not(None), h.from_stage != h.to_stage)
    history = (select(h.lead_id.label("lead_id"),
                      func.max(case((status_change, h.id))).label("change_id"),  # the latest status change
                      func.min(case((h.from_stage.is_(None), h.id))).label("created_id"))  # the lead being added
               .where(h.lead_id.is_not(None)))
    # the hand-overs: to a Salesperson (the pool only ever goes to one), to someone whose role then isn't known
    receiver = aliased(User, name="clock_receiver")
    pooled = t.from_user_id.is_(None)
    moves = (select(t.lead_id.label("lead_id"),
                    func.min(case((or_(pooled, salesperson_at(receiver, t.transferred_at)), t.transferred_at)))
                    .label("salesperson_at"),
                    func.min(case((and_(~pooled, ~role_known(receiver, t.transferred_at)), t.transferred_at)))
                    .label("unknown_at"),
                    func.min(t.transferred_at).label("first_at"),
                    func.min(t.id).label("first_id"),  # the first recorded hand-over: who had the lead before it
                    func.max(case((pooled, t.transferred_at))).label("pool_at"))
             .join(receiver, receiver.id == t.to_user_id))
    if lead_ids is not None:
        history = history.where(h.lead_id.in_(lead_ids))
        moves = moves.where(t.lead_id.in_(lead_ids))
    history = history.group_by(h.lead_id).subquery("clock_history")
    moves = moves.group_by(t.lead_id).subquery("clock_moves")
    change, created = aliased(StageHistory, name="clock_change"), aliased(StageHistory, name="clock_created")
    first = aliased(LeadTransfer, name="clock_first_move")
    # who had the lead when it was added: whoever the first recorded hand-over took it from (none: the pool), else
    # its owner now. Known only when every change of owner since it was added is recorded (see the module notes).
    first_owner_id = case((moves.c.first_id.is_not(None), first.from_user_id), else_=Lead.owner_id)
    first_owner = aliased(User, name="clock_first_owner")
    evidence = recorded_from()
    since_recorded = evidence.c.since
    added, changed = created.changed_at, change.changed_at
    owned_when_added = and_(added.is_not(None), first_owner.id.is_not(None))
    # never NULL (a missing time is "not known", not "unknown either way")
    owners_known = or_(and_(moves.c.first_id.is_(None), Lead.assigned_at.is_not(None)),  # added with assigned_at
                       and_(moves.c.first_id.is_not(None), first.from_user_id.is_(None)),  # first out of the pool
                       and_(added.is_not(None), since_recorded.is_not(None), added >= since_recorded))
    to_salesperson = and_(owned_when_added, owners_known, salesperson_at(first_owner, added))
    by_hand = Lead.uploaded_from.is_(None)
    # added by hand for a Salesperson: an assignment. An older upload that went straight to a Salesperson: one had it
    # from then, but the upload isn't dated as an assignment. Added before owners were recorded, or for someone whose
    # role then isn't known: unknown.
    added_for_salesperson = case((and_(to_salesperson, by_hand), added))
    uploaded_to_salesperson = case((and_(to_salesperson, ~by_hand), added))
    added_unknown = case((and_(owned_when_added, or_(~owners_known, ~role_known(first_owner, added))), added))
    # a status change while the lead was still with whoever it was added for (no hand-over before it), when that was
    # a Salesperson: one had it by then
    changed_with_salesperson = case((and_(changed.is_not(None),
                                          or_(owners_known, and_(since_recorded.is_not(None), changed >= since_recorded)),
                                          or_(moves.c.first_at.is_(None), moves.c.first_at > changed),
                                          first_owner.id.is_not(None), salesperson_at(first_owner, changed)), changed))

    facts = (select(Lead.id.label("id"), Lead.owner_id.label("owner_id"), Lead.stage.label("stage"),
                    changed.label("changed"),
                    func.coalesce(change.to_stage, created.to_stage).label("recorded"),  # the status the history says
                    added_for_salesperson.label("added_for_salesperson"),
                    uploaded_to_salesperson.label("uploaded_to_salesperson"),
                    added_unknown.label("added_unknown"),
                    changed_with_salesperson.label("changed_with_salesperson"),
                    moves.c.salesperson_at.label("moved_to_salesperson"),
                    moves.c.unknown_at.label("moved_unknown"),
                    moves.c.pool_at.label("pool_at"))
             .select_from(Lead)
             .outerjoin(history, history.c.lead_id == Lead.id)
             .outerjoin(change, change.id == history.c.change_id)
             .outerjoin(created, created.id == history.c.created_id)
             .outerjoin(moves, moves.c.lead_id == Lead.id)
             .outerjoin(first, first.id == moves.c.first_id)
             .outerjoin(first_owner, first_owner.id == first_owner_id)
             .join(evidence, true()))
    if lead_ids is not None:
        facts = facts.where(Lead.id.in_(lead_ids))
    f = step(facts, "clock_facts")
    steps = step(select(f.c.id, f.c.owner_id, f.c.stage, f.c.recorded, f.c.changed, f.c.pool_at,
                        # dated assignments to a Salesperson
                        earliest(f.c.added_for_salesperson, f.c.moved_to_salesperson).label("assigned"),
                        # steps that can't be dated or told
                        earliest(f.c.uploaded_to_salesperson, f.c.added_unknown, f.c.moved_unknown).label("unknown"),
                        # a Salesperson had it by then
                        earliest(f.c.added_for_salesperson, f.c.moved_to_salesperson, f.c.uploaded_to_salesperson,
                                 f.c.changed_with_salesperson).label("salesperson_by")), "clock_steps")
    g = steps.c
    first_assignment = case((and_(g.assigned.is_not(None), or_(g.unknown.is_(None), g.unknown > g.assigned)), g.assigned))
    start = case((and_(g.changed.is_not(None), g.salesperson_by.is_not(None), g.changed >= g.salesperson_by), g.changed),
                 else_=first_assignment)
    # a later assignment out of the pool (only if it had gone back there) starts it again
    since = case((and_(g.pool_at.is_not(None), or_(start.is_(None), g.pool_at > start)), g.pool_at), else_=start)
    timing = step(select(g.id, g.owner_id, g.stage, g.recorded, g.unknown, since.label("since")), "clock_timing")
    c = timing.c
    state = case((c.owner_id.is_(None), "not_started"),
                 (c.stage.not_in(LEAD_OPEN_STAGES), "closed"),
                 (or_(c.recorded.is_(None), c.recorded != c.stage), "not_recorded"),
                 (c.since.is_not(None), "timed"),
                 (c.unknown.is_not(None), "not_recorded"),
                 else_="not_started")  # never with a Salesperson
    ratings = []
    for stage, (attention, stalled) in clock.cutoffs.items():
        ratings += [(and_(c.stage == stage, c.since <= stalled), "stalled"),
                    (and_(c.stage == stage, c.since <= attention), "attention")]
    category = case((state != "timed", null()), *ratings, else_="on_track")
    return select(c.id.label("id"), case((state == "timed", c.since), else_=null()).label("since"),
                  state.label("state"), category.label("category")).subquery("stage_clock")


def order_by_clock(rows, direction: str) -> list:
    """Sort by time at the current status: desc = longest first, asc = shortest first. Leads without a time (Not
    started, Not recorded, closed) come after every timed lead either way, in NEUTRAL_ORDER."""
    timed_first = case((rows.c.state == "timed", 0), else_=1)
    neutral = case(*((rows.c.state == state, i) for i, state in enumerate(NEUTRAL_ORDER)), else_=len(NEUTRAL_ORDER))
    started = rows.c.since.asc() if direction == "desc" else rows.c.since.desc()  # earlier start = longer
    return [timed_first, started, neutral]


def stage_clocks(db: Session, clock: Clock, lead_ids: list[int]) -> dict[int, dict]:
    """The In stage of each of these leads (one page), with its elapsed seconds at the clock's reference time."""
    if not lead_ids:
        return {}
    rows = clock_rows(clock, lead_ids)
    return {lead_id: {"state": state, "since": since, "category": category,
                      "seconds": clock.seconds(since) if since is not None else None}
            for lead_id, since, state, category in db.execute(select(rows.c.id, rows.c.since, rows.c.state,
                                                                     rows.c.category)).all()}
