"""In stage on opportunities (app/stage_clock.py opportunity_clocks): the Opportunities list (GET /api/opportunities) and
an opportunity's page (GET /api/opportunities/{id}) give the same time in the current stage. It starts when the
opportunity is created or converted, a genuine stage change restarts it, edits and owner transfers don't, Won and Lost
keep counting from when they were reached, and history that doesn't explain the stage is Not recorded. The open stages
are rated (stage_clock.OPPORTUNITY_STAGE_DAYS); Won, Lost and Not recorded aren't.

Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin). The reference time is fixed (REF). All data is made up."""
from datetime import datetime, timedelta, timezone

import pytest

from app import stage_clock
from app.models import Opportunity, StageHistory
from app.stage_clock import OPPORTUNITY_STAGE_DAYS, to_stored
from conftest import finish_stage_tasks, login_as
from test_new_stages import NOTE, TASK, opportunity
from test_unassigned_pool import ASHA, PRIYA, RAVI, db  # noqa: F401

REF = datetime(2026, 12, 20, 15, 0, tzinfo=timezone.utc)
DAY = 86400
NOT_RECORDED = {"state": "not_recorded", "since": None, "seconds": None, "category": None}


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(stage_clock, "reference_time", lambda: REF)


def ago(**delta) -> datetime:
    return to_stored(REF - timedelta(**delta))


def set_latest(opp_id, at):
    """Move the opportunity's latest stage history row (its creation, or its latest stage change) to `at`."""
    with db() as s:
        s.query(StageHistory).filter_by(opportunity_id=opp_id).order_by(StageHistory.id.desc()).first().changed_at = at
        s.commit()


def listed(client, opp_id, user_id=ASHA):
    res = login_as(client, user_id).get("/api/opportunities")
    assert res.status_code == 200, res.text
    return {o["id"]: o["in_stage"] for o in res.json()}.get(opp_id, "not listed")


def detail(client, opp_id, user_id=ASHA):
    res = login_as(client, user_id).get(f"/api/opportunities/{opp_id}")
    assert res.status_code == 200, res.text
    return res.json()["in_stage"]


def clock(client, opp_id):
    """The list's and the page's In stage, checked to be the same."""
    in_list = listed(client, opp_id)
    assert detail(client, opp_id) == in_list
    return in_list


def test_it_starts_at_conversion_or_creation(client):
    converted = opportunity(login_as(client, RAVI))
    set_latest(converted["id"], ago(days=90))
    c = clock(client, converted["id"])
    assert (c["state"], c["seconds"], c["category"]) == ("timed", 90 * DAY, "stalled")
    created = login_as(client, RAVI).post("/api/opportunities", json={
        "name": "Synthetic direct deal", "account_name": "Clockwork Synthetic", "contact_first_name": "Dee",
        "contact_last_name": "Clock", "contact_email": "dee.clock@clockwork-synthetic.example", "note": NOTE,
        "task": TASK})
    assert created.status_code == 201, created.text
    opp_id = created.json()["opportunity"]["id"]
    set_latest(opp_id, ago(hours=5))
    assert (clock(client, opp_id)["state"], clock(client, opp_id)["seconds"]) == ("timed", 5 * 3600)


def test_a_stage_change_restarts_it_and_edits_or_transfers_do_not(client):
    opp = opportunity(login_as(client, RAVI))
    set_latest(opp["id"], ago(days=10))
    moved = client.put(f"/api/opportunities/{opp['id']}/stage", json={
        "task": TASK, "stage": "Discovery", "note": NOTE, "discovery_needs": "Synthetic reporting needs"})
    assert moved.status_code == 200, moved.text
    set_latest(opp["id"], ago(days=3))
    assert clock(client, opp["id"])["seconds"] == 3 * DAY
    before = clock(client, opp["id"])
    edited = client.put(f"/api/opportunities/{opp['id']}", json={"name": "Synthetic renamed deal"})
    assert edited.status_code == 200, edited.text
    moved_owner = login_as(client, ASHA).post("/api/opportunities/bulk-transfer",
                                              json={"opportunity_ids": [opp["id"]], "to_user_id": PRIYA})
    assert moved_owner.status_code == 200, moved_owner.text
    with db() as s:
        assert s.get(Opportunity, opp["id"]).owner_id == PRIYA
    assert clock(client, opp["id"]) == before  # neither restarted it (Last Modified changed; it isn't used)


def test_won_and_lost_keep_counting_from_when_they_were_reached(client):
    won, lost = opportunity(login_as(client, RAVI)), opportunity(login_as(client, RAVI))
    for stage, extra in (("Discovery", {"discovery_needs": "Synthetic needs"}), ("Proposal", {})):
        res = client.put(f"/api/opportunities/{won['id']}/stage", json={"task": TASK, "stage": stage, "note": NOTE, **extra})
        assert res.status_code == 200, res.text
        finish_stage_tasks(client, won["id"])
    assert client.post(f"/api/opportunities/{won['id']}/won", json={"task": TASK, "note": NOTE}).status_code == 200
    set_latest(won["id"], ago(days=3))
    res = client.post(f"/api/opportunities/{lost['id']}/lost", json={"lost_reason": "Price", "lost_notes": NOTE})
    assert res.status_code == 200, res.text
    set_latest(lost["id"], ago(hours=7))
    assert (clock(client, won["id"])["state"], clock(client, won["id"])["seconds"]) == ("timed", 3 * DAY)
    assert (clock(client, lost["id"])["state"], clock(client, lost["id"])["seconds"]) == ("timed", 7 * 3600)
    # reopening (no screen does it today): a change out of Lost starts the new stage's time
    with db() as s:
        s.add(StageHistory(opportunity_id=lost["id"], from_stage="Lost", to_stage="Proposal", changed_at=ago(hours=2),
                           changed_by_id=ASHA))
        s.get(Opportunity, lost["id"]).stage = "Proposal"
        s.commit()
    assert clock(client, lost["id"])["seconds"] == 2 * 3600


def test_history_that_doesnt_explain_the_stage_is_not_recorded(client):
    no_history, mismatch = opportunity(login_as(client, RAVI)), opportunity(login_as(client, RAVI))
    with db() as s:
        s.query(StageHistory).filter_by(opportunity_id=no_history["id"]).delete()
        s.get(Opportunity, mismatch["id"]).stage = "Proposal"  # its history only says Opportunity
        s.commit()
    assert clock(client, no_history["id"]) == NOT_RECORDED
    assert clock(client, mismatch["id"]) == NOT_RECORDED


def test_each_person_sees_only_the_opportunities_they_may_see(client):
    ravis, priyas = opportunity(login_as(client, RAVI)), opportunity(login_as(client, PRIYA))
    assert listed(client, priyas["id"], RAVI) == "not listed"  # the list keeps its visibility rules
    assert listed(client, ravis["id"], RAVI)["state"] == "timed"
    assert login_as(client, RAVI).get(f"/api/opportunities/{priyas['id']}").status_code in (403, 404)


# ---------- the agreed limits ----------

def at_stage(client, stage, elapsed):
    """A converted opportunity moved to `stage` (its history says so) `elapsed` before REF."""
    opp = opportunity(login_as(client, RAVI))
    if stage == "Opportunity":
        set_latest(opp["id"], to_stored(REF - elapsed))
    else:
        set_latest(opp["id"], to_stored(REF - elapsed - timedelta(days=1)))
        with db() as s:
            s.add(StageHistory(opportunity_id=opp["id"], from_stage="Opportunity", to_stage=stage,
                               changed_at=to_stored(REF - elapsed), changed_by_id=RAVI))
            s.get(Opportunity, opp["id"]).stage = stage
            s.commit()
    return opp["id"]


@pytest.mark.parametrize("stage", list(OPPORTUNITY_STAGE_DAYS))
def test_each_open_stage_is_rated_at_its_exact_limits(client, stage):
    attention, stalled = OPPORTUNITY_STAGE_DAYS[stage]
    assert (attention, stalled) == {"Opportunity": (2, 5), "Discovery": (7, 14), "Proposal": (14, 30)}[stage]
    second = timedelta(seconds=1)
    for expected, elapsed in (("on_track", timedelta(days=attention) - second), ("attention", timedelta(days=attention)),
                              ("attention", timedelta(days=stalled) - second), ("stalled", timedelta(days=stalled))):
        c = clock(client, at_stage(client, stage, elapsed))  # the list and the page agree
        assert (c["category"], c["seconds"]) == (expected, int(elapsed.total_seconds())), (stage, expected)


def test_won_lost_and_not_recorded_stay_unrated_and_the_rating_filters_nothing_else(client):
    won, lost = opportunity(login_as(client, RAVI)), opportunity(login_as(client, RAVI))
    with db() as s:
        for opp, stage in ((won, "Won"), (lost, "Lost")):
            s.add(StageHistory(opportunity_id=opp["id"], from_stage="Opportunity", to_stage=stage,
                               changed_at=ago(days=60), changed_by_id=RAVI))
            row = s.get(Opportunity, opp["id"])
            row.stage = stage
            if stage == "Lost":
                row.lost_reason = "Price"
        s.commit()
    unknown = opportunity(login_as(client, RAVI))
    with db() as s:
        s.query(StageHistory).filter_by(opportunity_id=unknown["id"]).delete()
        s.commit()
    stalled = at_stage(client, "Proposal", timedelta(days=31))
    for opp_id, state in ((won["id"], "timed"), (lost["id"], "timed"), (unknown["id"], "not_recorded")):
        c = clock(client, opp_id)
        assert (c["state"], c["category"]) == (state, None)  # 60 days Won / Lost: neutral, under All only
    assert clock(client, won["id"])["seconds"] == 60 * DAY
    assert clock(client, stalled)["category"] == "stalled"


# ---------- the Admin's limits (app_settings; defaults when unset) ----------

def limits_put(client, user_id, limits):
    return login_as(client, user_id).put("/api/opportunities/stage-limits", json={"limits": limits})


def test_the_admins_limits_rate_the_list_and_the_page_and_null_restores_the_default(client):
    opp = at_stage(client, "Proposal", timedelta(days=12))
    assert clock(client, opp)["category"] == "on_track"  # the default: needs attention at 14 days
    res = limits_put(client, ASHA, {"Proposal": [10, 12]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["limits"], body["custom"]) == ({"Opportunity": [2, 5], "Discovery": [7, 14], "Proposal": [10, 12]},
                                                ["Proposal"])
    assert body["defaults"]["Proposal"] == [14, 30] and body["updated_by"] == "Asha Rao"
    assert clock(client, opp)["category"] == "stalled"  # exactly 12 days: stalled; the list and the page agree
    assert clock(client, at_stage(client, "Proposal", timedelta(days=12) - timedelta(seconds=1)))["category"] == "attention"
    for user in (PRIYA, RAVI):  # everyone reads the same effective limits
        assert login_as(client, user).get("/api/opportunities/stage-limits").json()["limits"]["Proposal"] == [10, 12]
    # the same values as the defaults are not kept as custom; null puts a stage back to its default
    assert limits_put(client, ASHA, {"Proposal": None, "Discovery": [7, 14]}).json()["custom"] == []
    assert clock(client, opp)["category"] == "on_track"


@pytest.mark.parametrize("limits, status", [
    ({"Proposal": [-1, 5]}, 400), ({"Proposal": [5, 5]}, 400), ({"Proposal": [6, 5]}, 400),
    ({"Proposal": [1, 366]}, 400), ({"Proposal": [1]}, 400), ({"Won": [1, 2]}, 400), ({"Lost": None}, 400),
    ({"Proposal": [1.5, 3]}, 422), ({"Proposal": ["1", "3"]}, 422), ({"Proposal": [True, 3]}, 422),
])
def test_limits_are_whole_days_attention_below_stalled_for_open_stages_only(client, limits, status):
    assert limits_put(client, ASHA, limits).status_code == status
    assert login_as(client, ASHA).get("/api/opportunities/stage-limits").json()["custom"] == []  # nothing saved


def test_only_the_admin_changes_the_limits_and_zero_days_is_allowed(client):
    for user in (PRIYA, RAVI):
        res = limits_put(client, user, {"Opportunity": [1, 2]})
        assert res.status_code == 403 and "Only the Admin" in res.json()["detail"]
    assert limits_put(client, ASHA, {"Opportunity": [0, 1]}).json()["limits"]["Opportunity"] == [0, 1]
    opp = at_stage(client, "Opportunity", timedelta(seconds=1))
    assert clock(client, opp)["category"] == "attention"  # needs attention from 0 days: at once
