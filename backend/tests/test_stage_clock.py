"""In stage on the Leads list (app/stage_clock.py, GET /api/leads/page): when the clock starts (the first assignment to a
Salesperson) and restarts, what older history can and can't tell, the states, the ratings and their exact limits, real
elapsed time across DST, and the In stage filter and sort before paging, with every other filter and each role's list.

Users: 1 Priya (Manager: Ravi and Tara report to her), 2 Ravi (Salesperson), 3 Asha (Admin); the `team` fixture adds
Tara, Mona (Manager) with Sam, and Leo. The reference time is fixed (REF). Times the app stamps (assigned_at, which
also tells when this database started recording every change of owner) are set by the helpers as the app would, so
nothing depends on the real date. All leads and people are made up."""
from datetime import datetime, timedelta, timezone
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

from app import schemas, stage_clock
from app.models import Lead, LeadTransfer, StageHistory, User
from app.stage_clock import STAGE_DAYS, Clock, stage_clocks, to_stored
from conftest import login_as
from test_unassigned_pool import ASHA, PRIYA, RAVI, REASON, db, pool_rows, pooled_ids, team, upload  # noqa: F401

REF = datetime(2026, 12, 20, 15, 0, tzinfo=timezone.utc)  # "now" for every request in these tests
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
NOTE = "Synthetic stage note"
LOST_REASON = get_args(schemas.LostReason)[0]
DAY = 86400
UNTIMED = {"since": None, "seconds": None, "category": None}


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(stage_clock, "reference_time", lambda: REF)


def ago(**delta) -> datetime:
    """A stored server time this long before REF."""
    return to_stored(REF - timedelta(**delta))


def own_lead(client, user_id, first="Omar", **extra) -> int:
    res = login_as(client, user_id).post("/api/leads", json={"first_name": first, "last_name": "Clock",
                                                             "company": "Clock Synthetic Co", "source": "Website",
                                                             "email": f"{first.lower()}@clock-synthetic.example", **extra})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def set_times(lead_id, created=None, change=None, transfer=None):
    """Move the lead's recorded moments: its creation row, its latest status change row, its latest hand-over, and
    assigned_at with them as the app stamps it (when the lead was added, then at each Assign or Transfer)."""
    with db() as s:
        lead = s.get(Lead, lead_id)
        rows = s.query(StageHistory).filter_by(lead_id=lead_id).order_by(StageHistory.id).all()
        moved = s.query(LeadTransfer).filter_by(lead_id=lead_id).order_by(LeadTransfer.id.desc()).first()
        if created is not None:
            next(r for r in rows if r.from_stage is None).changed_at = created
            if moved is None and lead.assigned_at is not None:
                lead.assigned_at = created
        if change is not None:
            [r for r in rows if r.from_stage is not None][-1].changed_at = change
        if transfer is not None:
            moved.transferred_at = transfer
            if lead.assigned_at is not None:
                lead.assigned_at = transfer
        s.commit()


def add_history(lead_id, from_stage, to_stage, at, stage=None):
    with db() as s:
        s.add(StageHistory(lead_id=lead_id, from_stage=from_stage, to_stage=to_stage, changed_at=at, changed_by_id=ASHA))
        if stage:
            s.get(Lead, lead_id).stage = stage
        s.commit()


def hand_over(lead_id, from_user, to_user, at, stamped=True):
    """A recorded transfer at a given time: as transfer_lead / Assign save it (assigned_at too), or stamped=False as
    Users > Transfer records moves a lead (no assigned_at)."""
    with db() as s:
        s.add(LeadTransfer(lead_id=lead_id, from_user_id=from_user, to_user_id=to_user, transferred_by_id=ASHA,
                           transferred_at=at))
        lead = s.get(Lead, lead_id)
        lead.owner_id = to_user
        if stamped:
            lead.assigned_at = at
        s.commit()


def recording_since(at):
    """The earliest record in this database that only a version recording every change of owner writes: here a
    closed lead the Admin added at `at` (its assigned_at)."""
    with db() as s:
        s.add(Lead(first_name="Eve", last_name="Stamp", company="Evidence Synthetic Co", source="Website", stage="Lost",
                   lost_reason=LOST_REASON, owner_id=ASHA, created_by_id=ASHA, assigned_at=at))
        s.commit()


def old_version_lead(owner_id, created, stage="New", uploaded=False) -> int:
    """A lead an older version added: owned from the start, no assigned_at."""
    with db() as s:
        lead = Lead(first_name="Ola", last_name="Older", company="Older Synthetic Co", source="Upload" if uploaded
                    else "Website", stage=stage, owner_id=owner_id, created_by_id=owner_id or ASHA,
                    phone="+91 98765 00002", uploaded_from="older.csv" if uploaded else None)
        s.add(lead)
        s.flush()
        s.add(StageHistory(lead_id=lead.id, from_stage=None, to_stage="New", changed_by_id=owner_id or ASHA,
                           changed_at=created))
        s.commit()
        return lead.id


def role_changed(user_id, at):
    with db() as s:
        s.get(User, user_id).role_changed_at = at
        s.commit()


def page(client, user_id=ASHA, **params):
    res = login_as(client, user_id).get("/api/leads/page", params={"view": "all", "limit": 500, **params})
    assert res.status_code == 200, res.text
    return res.json()


def clock(client, lead_id, user_id=ASHA):
    [item] = [l for l in page(client, user_id)["items"] if l["id"] == lead_id]
    return item["in_stage"]


def timed(client, lead_id):
    c = clock(client, lead_id)
    assert c["state"] == "timed", c
    return c["seconds"], c["category"]


def since(c) -> datetime:
    return datetime.fromisoformat(c["since"]).astimezone(timezone.utc)


def move(client, lead_id, stage, **extra):
    res = client.put(f"/api/leads/{lead_id}/stage", json={"task": TASK, "stage": stage, "note": NOTE, **extra})
    assert res.status_code == 200, res.text
    return res.json()


# ---------- when it starts: the first assignment to a Salesperson ----------

def test_an_upload_into_the_pool_is_not_started_and_is_in_no_category(client, team):
    upload(login_as(client, ASHA), pool_rows(2))
    for lead_id in pooled_ids(client):
        set_times(lead_id, created=ago(days=40))  # uploaded long ago: still not started
        assert clock(client, lead_id) == {"state": "not_started", **UNTIMED}
    for category in ("on_track", "attention", "stalled"):
        assert page(client, in_stage=category)["total"] == 0


def test_single_bulk_and_approved_assignments_start_the_clock_at_the_assignment(client, team):
    upload(login_as(client, ASHA), pool_rows(3))
    single, bulk, requested = sorted(pooled_ids(client))
    for lead_id in (single, bulk, requested):
        set_times(lead_id, created=ago(days=30))  # the upload: not the start
    assert login_as(client, PRIYA).post(f"/api/leads/{single}/assign", json={"to_user_id": team["tara"]}).status_code == 200
    res = login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": [bulk], "to_user_id": RAVI})
    assert res.status_code == 200 and res.json()["assigned"] == 1, res.text
    asked = login_as(client, RAVI).post(f"/api/leads/{requested}/transfer-requests", json={"reason": REASON})
    assert asked.status_code == 201, asked.text
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{asked.json()['id']}/approve", json={}).status_code == 200
    for lead_id, hours in ((single, 3), (bulk, 30), (requested, 2 * 24 + 1)):
        set_times(lead_id, transfer=ago(hours=hours))
        c = clock(client, lead_id)
        assert (c["state"], c["seconds"], since(c)) == ("timed", hours * 3600, REF - timedelta(hours=hours))
    assert [clock(client, i)["category"] for i in (single, bulk, requested)] == ["on_track", "on_track", "attention"]


def test_a_lead_added_for_a_salesperson_starts_when_it_was_added(client, team):
    mine = own_lead(client, RAVI)
    for_tara = own_lead(client, PRIYA, "Tia", owner_id=team["tara"])  # added by her Manager, owned by Tara
    for lead_id in (mine, for_tara):
        set_times(lead_id, created=ago(hours=5))
        assert timed(client, lead_id) == (5 * 3600, "on_track")


def test_an_admins_or_managers_own_lead_starts_only_when_a_salesperson_gets_it(client, team):
    managers, admins = own_lead(client, PRIYA, "Pia"), own_lead(client, ASHA, "Ada")
    for lead_id in (managers, admins):
        set_times(lead_id, created=ago(days=20))
        assert clock(client, lead_id) == {"state": "not_started", **UNTIMED}  # owned, but no Salesperson yet
    move(login_as(client, PRIYA), managers, "Nurturing")  # worked on by the Manager: still not started
    set_times(managers, change=ago(days=15))
    assert clock(client, managers)["state"] == "not_started"
    hand_over(managers, PRIYA, RAVI, ago(days=2))  # the first assignment to a Salesperson
    assert timed(client, managers) == (2 * DAY, "on_track")
    hand_over(managers, RAVI, PRIYA, ago(days=1))  # back to the Manager: the clock keeps going
    assert timed(client, managers) == (2 * DAY, "on_track")
    for category in ("on_track", "attention", "stalled"):  # not started leads are in no category
        assert admins not in [l["id"] for l in page(client, in_stage=category)["items"]]


def test_a_status_change_restarts_it_and_a_transfer_does_not(client, team):
    recording_since(ago(days=60))
    lead_id = own_lead(client, RAVI)
    set_times(lead_id, created=ago(days=6))
    assert clock(client, lead_id)["category"] == "stalled"  # New for 6 days
    move(login_as(client, RAVI), lead_id, "Nurturing")
    set_times(lead_id, change=ago(days=3))
    assert timed(client, lead_id) == (3 * DAY, "on_track")
    before = clock(client, lead_id)
    res = login_as(client, ASHA).post(f"/api/leads/{lead_id}/transfer", json={"to_user_id": team["tara"], "note": "Cover"})
    assert res.status_code == 200, res.text
    assert res.json()["owner_id"] == team["tara"] and res.json()["assigned_at"]  # assigned_at moved, the clock didn't
    assert clock(client, lead_id) == before
    # the Assistant's and the bulk transfer go through the same transfer_lead: no restart either, to anyone
    for to in (RAVI, PRIYA):
        res = login_as(client, ASHA).post("/api/leads/bulk-transfer", json={"lead_ids": [lead_id], "to_user_id": to})
        assert res.status_code == 200, res.text
        assert clock(client, lead_id) == before


def test_a_demo_reschedule_is_not_a_status_change(client):
    lead_id = own_lead(client, RAVI)
    move(client, lead_id, "Demo", demo_date="2030-03-05T11:00:00", completed_stages=["Nurturing"])
    set_times(lead_id, created=ago(days=6), change=ago(days=4))
    res = client.post(f"/api/leads/{lead_id}/cancel-demo", json={"reschedule_to": "2030-03-06T11:00:00"})
    assert res.status_code == 200, res.text
    assert [h["to_stage"] for h in res.json()["history"]][-1] == "Demo"  # Demo -> Demo recorded
    assert timed(client, lead_id) == (4 * DAY, "on_track")  # still from the move to Demo (attention at 5)


# ---------- roles: known only when no change was recorded after the moment ----------

def test_a_role_changed_after_the_assignment_leaves_the_start_unknown(client, team):
    before_change = own_lead(client, RAVI, "Bea")
    set_times(before_change, created=ago(days=10))
    role_changed(RAVI, ago(days=5))  # e.g. made a Salesperson then: his role on day 10 isn't known
    assert clock(client, before_change) == {"state": "not_recorded", **UNTIMED}
    after_change = own_lead(client, RAVI, "Ava")
    set_times(after_change, created=ago(days=3))  # added after his latest role change: he was a Salesperson
    assert timed(client, after_change) == (3 * DAY, "attention")
    move(login_as(client, RAVI), before_change, "Nurturing")  # a status change while he is known to have had it
    set_times(before_change, change=ago(days=2))
    assert timed(client, before_change) == (2 * DAY, "on_track")


def test_a_transfer_to_someone_whose_role_then_is_unknown_is_not_used(client, team):
    recording_since(ago(days=60))
    managers = own_lead(client, PRIYA, "Pam")
    set_times(managers, created=ago(days=12))
    hand_over(managers, PRIYA, team["tara"], ago(days=6))
    role_changed(team["tara"], ago(days=4))  # Tara's role on day 6 isn't known
    assert clock(client, managers) == {"state": "not_recorded", **UNTIMED}
    role_changed(team["tara"], ago(days=8))  # changed before the transfer: she was a Salesperson then
    assert timed(client, managers) == (6 * DAY, "stalled")
    role_changed(PRIYA, ago(days=11))  # Priya's own role when it was added (day 12) isn't known now either
    assert clock(client, managers)["state"] == "not_recorded"


# ---------- older leads: only what the history says ----------

def legacy_upload(owner_id=PRIYA, stage="New", created=None) -> int:
    """An upload from before the Unassigned Pool: straight to an owner, no assigned_at."""
    return old_version_lead(owner_id, created or ago(days=30), stage=stage, uploaded=True)


def test_an_older_upload_to_a_manager_is_not_recorded_and_restarts_on_a_known_status_change(client, team):
    recording_since(ago(days=20))  # its owners were recorded from day 20, not since it was uploaded (day 30)
    untouched, handed = legacy_upload(), legacy_upload()
    hand_over(handed, PRIYA, RAVI, ago(days=5))
    # who had them before day 20 isn't known: not "only ever the Manager", and the transfer isn't a first assignment
    assert clock(client, untouched) == {"state": "not_recorded", **UNTIMED}
    assert clock(client, handed) == {"state": "not_recorded", **UNTIMED}
    add_history(handed, "New", "Nurturing", ago(days=2), stage="Nurturing")  # while Ravi is known to have it
    assert timed(client, handed) == (2 * DAY, "on_track")
    hand_over(handed, RAVI, PRIYA, ago(days=1))  # an established clock: later transfers don't reset it
    assert timed(client, handed) == (2 * DAY, "on_track")


def test_an_older_upload_to_a_salesperson_is_not_dated_by_its_upload_or_a_later_transfer(client, team):
    recording_since(ago(days=20))
    untouched, handed, worked, worked_early = (legacy_upload(RAVI) for _ in range(4))
    hand_over(handed, RAVI, team["tara"], ago(days=1))  # not the original assignment: Ravi had it from the upload
    add_history(worked, "New", "Nurturing", ago(days=8), stage="Nurturing")  # while Ravi is known to have had it
    add_history(worked_early, "New", "Nurturing", ago(days=25), stage="Nurturing")  # before owners were recorded
    for lead_id in (untouched, handed, worked_early):
        assert clock(client, lead_id) == {"state": "not_recorded", **UNTIMED}
    assert timed(client, worked) == (8 * DAY, "attention")


def test_an_environment_that_got_the_recording_version_after_2_november(client, team):
    """This database started recording every change of owner on 1 Dec 2026 (its first stamped record), a month after
    the version was written: what happened here between 2 Nov and 1 Dec isn't taken as recorded."""
    deployed = datetime(2026, 12, 1, 9, 0)
    before = datetime(2026, 11, 15, 10, 0)  # after the commit date, before this database had the version
    sellers = old_version_lead(RAVI, before)
    managers = old_version_lead(PRIYA, before)
    moved = old_version_lead(PRIYA, before)
    hand_over(moved, PRIYA, RAVI, datetime(2026, 11, 20, 10, 0), stamped=False)  # moved by the older version
    worked = old_version_lead(RAVI, before)
    add_history(worked, "New", "Nurturing", ago(days=4), stage="Nurturing")  # a status change after 1 Dec
    pooled = old_version_lead(None, datetime(2026, 11, 30, 10, 0), uploaded=True)
    hand_over(pooled, None, RAVI, deployed)  # the first assignment out of the pool here: the first stamped record
    with db() as s:
        s.add_all([Lead(first_name=first, last_name="Newer", company="Newer Synthetic Co", source="Website",
                        stage="New", owner_id=owner, created_by_id=owner, assigned_at=ago(days=3)) for first, owner
                   in (("Nora", RAVI), ("Nash", PRIYA))])
        s.commit()
        added = {l.first_name: l.id for l in s.query(Lead).filter(Lead.company == "Newer Synthetic Co")}
    for lead_id in added.values():
        add_history(lead_id, None, "New", ago(days=3))
    for lead_id in (sellers, managers, moved):
        assert clock(client, lead_id) == {"state": "not_recorded", **UNTIMED}, lead_id
    assert timed(client, worked) == (4 * DAY, "on_track")  # recorded from 1 Dec: a known status change
    assert clock(client, pooled)["seconds"] == int((REF - deployed.astimezone(timezone.utc)).total_seconds())
    assert timed(client, added["Nora"]) == (3 * DAY, "attention")  # added after it, for a Salesperson
    assert clock(client, added["Nash"]) == {"state": "not_started", **UNTIMED}  # a Manager's own, with the evidence


def test_without_any_evidence_owned_leads_are_not_recorded_rather_than_not_started(client, team):
    managers, sellers = old_version_lead(PRIYA, ago(days=10)), old_version_lead(RAVI, ago(days=10))
    for lead_id in (managers, sellers):  # nothing in this database shows it records every change of owner
        assert clock(client, lead_id) == {"state": "not_recorded", **UNTIMED}


def test_leads_from_before_this_database_recorded_every_owner_change(client, team):
    recording_since(ago(days=20))
    untouched, worked_early, worked_later, handed = (old_version_lead(RAVI, ago(days=30)) for _ in range(4))
    add_history(worked_early, "New", "Nurturing", ago(days=25), stage="Nurturing")
    add_history(worked_later, "New", "Nurturing", ago(days=3), stage="Nurturing")
    hand_over(handed, RAVI, team["tara"], ago(days=1))
    assert clock(client, untouched) == {"state": "not_recorded", **UNTIMED}  # the owner then isn't known
    assert clock(client, worked_early)["state"] == "not_recorded"
    assert timed(client, worked_later) == (3 * DAY, "on_track")  # a change while a Salesperson is known to have had it
    assert clock(client, handed)["state"] == "not_recorded"  # the transfer isn't shown as its first assignment


def test_no_history_or_history_that_disagrees_is_not_recorded(client):
    no_history, mismatch = own_lead(client, RAVI, "Nia"), own_lead(client, RAVI, "Mia")
    with db() as s:
        s.query(StageHistory).filter_by(lead_id=no_history).delete()
        s.get(Lead, mismatch).stage = "Revisit"  # its status says Revisit, its history only New
        s.commit()
    assert clock(client, no_history) == {"state": "not_recorded", **UNTIMED}
    assert clock(client, mismatch) == {"state": "not_recorded", **UNTIMED}


# ---------- closed, reopened, back in the pool ----------

def test_closed_leads_are_not_timed_and_a_reopened_lead_starts_again(client):
    lost, unqualified = own_lead(client, RAVI, "Lou"), own_lead(client, RAVI, "Uma")
    assert client.post(f"/api/leads/{lost}/lost", json={"lost_reason": LOST_REASON, "lost_notes": NOTE}).status_code == 200
    assert client.post(f"/api/leads/{unqualified}/unqualified", json={"reason": "No budget", "notes": NOTE}).status_code == 200
    for lead_id in (lost, unqualified):
        set_times(lead_id, created=ago(days=40), change=ago(days=35))
        assert clock(client, lead_id) == {"state": "closed", **UNTIMED}
    with db() as s:  # a converted lead too
        s.get(Lead, lost).stage = "Converted"
        s.commit()
    assert clock(client, lost)["state"] == "closed"
    assert page(client, in_stage="stalled")["total"] == 0
    reopened = client.post(f"/api/leads/{unqualified}/reopen", json={"note": "Budget approved now", "task": TASK})
    assert reopened.status_code == 200, reopened.text
    set_times(unqualified, change=ago(hours=1))
    assert timed(client, unqualified) == (3600, "on_track")


def test_a_lead_back_in_the_pool_is_not_started_and_its_next_assignment_starts_it(client, team):
    upload(login_as(client, ASHA), pool_rows(1))
    [lead_id] = pooled_ids(client)
    set_times(lead_id, created=ago(days=25))
    assert login_as(client, ASHA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI}).status_code == 200
    move(login_as(client, RAVI), lead_id, "Nurturing")
    set_times(lead_id, transfer=ago(days=20), change=ago(days=10))
    with db() as s:  # no code does this today; if something did:
        s.get(Lead, lead_id).owner_id = None
        s.commit()
    assert clock(client, lead_id)["state"] == "not_started"
    hand_over(lead_id, None, team["tara"], ago(days=2))
    assert clock(client, lead_id)["seconds"] == 2 * DAY


# ---------- the limits, short times and DST ----------

@pytest.mark.parametrize("stage", list(STAGE_DAYS))
def test_each_status_is_rated_at_its_exact_limits(client, stage):
    attention, stalled = STAGE_DAYS[stage]
    cases = {"on_track": timedelta(days=attention) - timedelta(seconds=1), "attention": timedelta(days=attention),
             "attention ": timedelta(days=stalled) - timedelta(seconds=1), "stalled": timedelta(days=stalled)}
    for i, (expected, elapsed) in enumerate(cases.items()):
        lead_id = own_lead(client, RAVI, f"Lim{chr(65 + i)}")
        if stage != "New":
            set_times(lead_id, created=to_stored(REF - elapsed - timedelta(days=1)))
            add_history(lead_id, "New", stage, to_stored(REF - elapsed), stage=stage)
        else:
            set_times(lead_id, created=to_stored(REF - elapsed))
        c = clock(client, lead_id)
        assert (c["category"], c["seconds"]) == (expected.strip(), int(elapsed.total_seconds())), (stage, expected)


def test_short_times_come_back_in_seconds_for_the_badge(client):
    for i, elapsed in enumerate((timedelta(minutes=5), timedelta(minutes=59, seconds=59), timedelta(hours=1),
                                 timedelta(hours=23, minutes=59))):
        lead_id = own_lead(client, RAVI, f"Sho{chr(65 + i)}")
        set_times(lead_id, created=to_stored(REF - elapsed))
        assert clock(client, lead_id)["seconds"] == int(elapsed.total_seconds())
    future = own_lead(client, RAVI, "Fut")  # a clock a little ahead never shows a negative time
    set_times(future, created=to_stored(REF + timedelta(minutes=2)))
    assert clock(client, future)["seconds"] == 0


def test_elapsed_time_is_real_time_across_a_dst_change(client):
    """New York: 7 Nov 2027 02:00 EDT -> 01:00 EST. A lead stored at 6 Nov 12:30 (EDT) seen on 8 Nov 12:00 (EST) has
    been there 2 days and 30 minutes of real time (the clock face says 1 day 23 hours 30 minutes)."""
    zone = ZoneInfo("America/New_York")
    clock_at = Clock(datetime(2027, 11, 8, 12, 0, tzinfo=zone), zone)
    assert clock_at.cutoffs["New"][0] == datetime(2027, 11, 6, 13, 0)  # 2 days ago, as stored (EDT then)
    lead_id = own_lead(client, RAVI)
    set_times(lead_id, created=datetime(2027, 11, 6, 12, 30))
    with db() as s:
        [value] = stage_clocks(s, clock_at, [lead_id]).values()
    assert (value["seconds"], value["category"]) == (2 * DAY + 1800, "attention")
    # and spring forward: 8 Mar 2026 02:00 EST -> 03:00 EDT
    spring = Clock(datetime(2026, 3, 9, 12, 0, tzinfo=zone), zone)
    assert spring.seconds(datetime(2026, 3, 7, 12, 30)) == 2 * DAY - 3600 - 1800
    assert spring.cutoffs["New"][0] == datetime(2026, 3, 7, 11, 0)


# ---------- the filter and the sort, before paging ----------

@pytest.fixture
def mixed(client, team):
    """Timed leads of Ravi's and Tara's at each rating, pooled leads, an older upload, a closed lead and a Manager's."""
    leads = {}
    for owner, first, stage, days in ((RAVI, "Rna", "New", 1), (RAVI, "Rnb", "New", 3), (RAVI, "Rnc", "New", 9),
                                      (RAVI, "Rnd", "Nurturing", 8), (team["tara"], "Tna", "New", 6),
                                      (team["tara"], "Tnb", "Demo", 2), (RAVI, "Rne", "Revisit", 31)):
        lead_id = own_lead(client, PRIYA, first, owner_id=owner, **({"phone_country": "IN"} if owner == RAVI else {}))
        if stage == "New":
            set_times(lead_id, created=ago(days=days))
        else:
            set_times(lead_id, created=ago(days=days + 1))
            add_history(lead_id, "New", stage, ago(days=days), stage=stage)
        leads[first] = lead_id
    upload(login_as(client, ASHA), pool_rows(2))
    leads["pool"] = pooled_ids(client)
    leads["legacy"] = legacy_upload(owner_id=RAVI)  # not recorded
    leads["closed"] = own_lead(client, RAVI, "Cla")
    with db() as s:
        s.get(Lead, leads["closed"]).stage = "Lost"
        s.get(Lead, leads["closed"]).lost_reason = LOST_REASON
        s.commit()
    leads["manager"] = own_lead(client, PRIYA, "Pma")  # owned, never with a Salesperson: not started
    return leads


def test_the_filter_counts_and_pages_the_whole_list(client, mixed):
    expected = {"on_track": ["Rna", "Tnb"], "attention": ["Rnb", "Rnd"], "stalled": ["Rnc", "Tna", "Rne"]}
    for category, names in expected.items():
        full = page(client, in_stage=category)
        assert full["total"] == len(names) and sorted(l["id"] for l in full["items"]) == sorted(mixed[n] for n in names)
        assert {l["in_stage"]["category"] for l in full["items"]} == {category}
        seen = []
        for offset in range(0, len(names), 2):
            one = page(client, in_stage=category, limit=2, offset=offset)
            assert one["total"] == len(names)
            seen += [l["id"] for l in one["items"]]
        assert sorted(seen) == sorted(mixed[n] for n in names)
    assert page(client)["total"] == 7 + 2 + 3  # All: the untimed ones stay in the list
    assert login_as(client, ASHA).get("/api/leads/page", params={"in_stage": "late"}).status_code == 400


def test_the_sort_goes_both_ways_with_untimed_leads_last(client, mixed):
    longest = ["Rne", "Rnc", "Rnd", "Tna", "Rnb", "Tnb", "Rna"]  # 31, 9, 8, 6, 3, 2, 1 days
    # not started (newest first), not recorded, closed
    untimed = [mixed["manager"], *sorted(mixed["pool"], reverse=True), mixed["legacy"], mixed["closed"]]
    for direction, order in (("desc", longest), ("asc", longest[::-1])):
        ids = [l["id"] for l in page(client, view="all", sort="in_stage", direction=direction)["items"]]
        assert ids == [mixed[n] for n in order] + untimed, direction
        paged = []
        for offset in range(0, len(ids), 3):
            paged += [l["id"] for l in page(client, view="all", sort="in_stage", direction=direction, limit=3,
                                            offset=offset)["items"]]
        assert paged == ids
    stalled_longest = [l["id"] for l in page(client, sort="in_stage", direction="desc", in_stage="stalled")["items"]]
    assert stalled_longest == [mixed["Rne"], mixed["Rnc"], mixed["Tna"]]


def test_the_filter_combines_with_views_filters_search_and_roles(client, mixed, team):
    def matching(user_id, **params):
        everything = page(client, user_id, **params)["items"]
        for category in ("on_track", "attention", "stalled"):
            filtered = page(client, user_id, in_stage=category, **params)
            want = sorted(l["id"] for l in everything if (l["in_stage"] or {}).get("category") == category)
            assert filtered["total"] == len(want) and sorted(l["id"] for l in filtered["items"]) == want, (user_id, params)

    for user_id in (ASHA, PRIYA, RAVI, team["tara"]):
        for params in ({"view": "all_open"}, {"view": "my_open"}, {"view": "all", "stage": "New"},
                       {"view": "all", "region": "IN"}, {"view": "all", "owner": str(RAVI)}, {"view": "all", "search": "Rn"},
                       {"view": "all_open", "stage": "New", "assigned": "true"}):  # a Kanban column
            matching(user_id, **params)
    ravi_stalled = page(client, RAVI, view="all_open", in_stage="stalled")["items"]
    assert sorted(l["id"] for l in ravi_stalled) == sorted([mixed["Rnc"], mixed["Rne"]])  # not Tara's
    # a Salesperson sees the pool in All Open Leads, as Not started with its contacts still hidden
    pooled = [l for l in page(client, RAVI, view="all_open")["items"] if l["id"] in mixed["pool"]]
    assert pooled and all(l["in_stage"]["state"] == "not_started" and l["email"] is None for l in pooled)


def test_listing_writes_nothing_and_leaves_last_modified_alone(client, mixed):
    def snapshot():
        with db() as s:
            return (sorted((l.id, l.updated_at, l.assigned_at, l.stage, l.owner_id) for l in s.query(Lead)),
                    s.query(StageHistory).count(), s.query(LeadTransfer).count(),
                    sorted((u.id, u.role, u.role_changed_at) for u in s.query(User)))

    before = snapshot()
    for params in ({}, {"in_stage": "stalled"}, {"sort": "in_stage", "direction": "desc"},
                   {"sort": "in_stage", "direction": "asc", "in_stage": "attention"}):
        page(client, **params)
        page(client, RAVI, view="all_open", **params)
    assert snapshot() == before


def test_one_reference_time_per_response(client, mixed, monkeypatch):
    calls = []
    monkeypatch.setattr(stage_clock, "reference_time", lambda: calls.append(1) or REF)
    page(client, sort="in_stage", in_stage="stalled")
    assert len(calls) == 1


# ---------- the lead page: the same clock as the list ----------

def detail(client, lead_id, user_id=ASHA):
    res = login_as(client, user_id).get(f"/api/leads/{lead_id}")
    assert res.status_code == 200, res.text
    return res.json()["in_stage"]


def test_the_lead_page_shows_the_same_clock_as_the_list(client, mixed, team):
    listed = {l["id"]: l["in_stage"] for l in page(client)["items"]}
    states = set()
    for lead_id, clock_listed in listed.items():
        assert detail(client, lead_id) == clock_listed, lead_id  # same start, seconds, rating and state
        states.add((clock_listed["state"], clock_listed["category"]))
    assert states >= {("timed", "on_track"), ("timed", "attention"), ("timed", "stalled"), ("not_started", None),
                      ("not_recorded", None), ("closed", None)}
    # a Salesperson opening a pooled lead (contacts hidden): Not started there too
    pooled = mixed["pool"][0]
    assert detail(client, pooled, RAVI) == {"state": "not_started", **UNTIMED}


def test_the_lead_page_follows_status_changes_and_not_transfers(client, team):
    lead_id = own_lead(client, RAVI)
    set_times(lead_id, created=ago(days=6))
    assert detail(client, lead_id)["category"] == "stalled"
    moved = move(login_as(client, RAVI), lead_id, "Nurturing")  # the page's own answer after the change
    with db() as s:
        changed_at = s.query(StageHistory).filter_by(lead_id=lead_id, to_stage="Nurturing").one().changed_at
    # restarted at the change (its time as this test database stored it)
    assert moved["in_stage"]["state"] == "timed"
    assert datetime.fromisoformat(moved["in_stage"]["since"]).replace(tzinfo=None) == changed_at
    set_times(lead_id, change=ago(days=8))
    before = detail(client, lead_id)
    assert (before["seconds"], before["category"]) == (8 * DAY, "attention")
    res = login_as(client, ASHA).post(f"/api/leads/{lead_id}/transfer", json={"to_user_id": team["tara"], "note": "Cover"})
    assert res.status_code == 200 and res.json()["in_stage"] == before  # the transfer's answer: the same clock
    assert detail(client, lead_id) == before

