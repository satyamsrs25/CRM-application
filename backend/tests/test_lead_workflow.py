"""Leads: deleting sends no email (the bell, the Activity Log and Deleted Leads still have it), the Admin's Lead Status
limits (their own setting, used by the list, its filter and counts, the board and a lead's page), the Owner filter
with several people and the Unassigned Pool, the Stalled count, and saved Leads views (Update View, kept apart from
Opportunities views).

Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin). The reference time is fixed (REF). All data is made up."""
from datetime import timedelta

import pytest

from app import mailer, stage_clock
from app.models import Notification, User
from conftest import login_as
from test_stage_clock import REF, ago, clock, own_lead, page, set_times
from test_unassigned_pool import ASHA, PRIYA, RAVI, db, pool_rows, pooled_ids, team, upload  # noqa: F401

DAY = 86400


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(stage_clock, "reference_time", lambda: REF)


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append((tuple(to), subject)))
    return sent


def everyone_wants_email():
    """Every email setting on, so a deletion email would be sent if any were made."""
    with db() as s:
        for user in s.query(User):
            user.email_stage_updates = user.email_assignments = user.email_reminders = True
        s.commit()


def bell(user_id) -> list[str]:
    with db() as s:
        return [n.title for n in s.query(Notification).filter_by(user_id=user_id)]


# ---------- 2. deleting leads: no email ----------

def test_deleting_leads_one_or_several_sends_no_email_but_keeps_the_bell_log_and_restore(client, mails):
    everyone_wants_email()
    single = own_lead(client, RAVI, "Della")
    several = [own_lead(client, RAVI, name) for name in ("Bulka", "Bulkb")]
    mails.clear()
    assert login_as(client, ASHA).delete(f"/api/leads/{single}").status_code == 200
    assert login_as(client, PRIYA).post("/api/leads/bulk-delete", json={"lead_ids": several}).json()["deleted"] == 2
    assert mails == []  # no email for any deletion, whoever deleted and however
    # the bell still tells the owner and the Managers / Admin (as before)
    assert "Lead deleted" in bell(RAVI) and "Leads deleted" in bell(RAVI)
    assert "Lead deleted" in bell(PRIYA) and "Leads deleted" in bell(ASHA)
    # the Activity Log and Deleted Leads keep them; restoring still works
    log = login_as(client, ASHA).get("/api/activity-log").json()
    assert sum(r["action"] == "Lead deleted" for r in log) == 3
    kept = client.get("/api/deleted-leads").json()["items"]
    assert len(kept) == 3
    restored = client.post("/api/deleted-leads/restore", json={"ids": [kept[0]["id"]]}).json()
    assert len(restored["restored"]) == 1 and mails == []
    # other emails are untouched: an assignment still sends one
    lead = own_lead(client, RAVI, "Keepa")
    mails.clear()
    assert login_as(client, ASHA).post(f"/api/leads/{lead}/transfer", json={"to_user_id": PRIYA}).status_code == 200
    assert any(to == ("priya@crm.test",) for to, _ in mails)


# ---------- 4. the Lead Status limits ----------

def limits_put(client, user_id, limits, kind="leads"):
    return login_as(client, user_id).put(f"/api/{kind}/stage-limits", json={"limits": limits})


def test_the_admins_lead_limits_rate_the_list_filter_count_and_page_alike_and_stay_apart_from_opportunities(client):
    lead = own_lead(client, RAVI, "Nadia")
    set_times(lead, created=ago(days=3))  # New for 3 days: needs attention by default (2 / 5)
    assert clock(client, lead)["category"] == "attention"
    res = limits_put(client, ASHA, {"New": [1, 3]})
    assert res.status_code == 200, res.text
    assert res.json()["limits"] == {"New": [1, 3], "Nurturing": [7, 14], "Revisit": [14, 30], "Demo": [5, 10]}
    assert clock(client, lead)["category"] == "stalled"  # exactly 3 days: stalled
    detail = login_as(client, ASHA).get(f"/api/leads/{lead}").json()["in_stage"]
    assert detail == clock(client, lead)  # the lead's page agrees
    assert [x["id"] for x in page(client, in_stage="stalled")["items"]] == [lead]
    assert page(client, with_stalled="true")["stalled"] == 1
    # the opportunities' limits are separate
    assert login_as(client, ASHA).get("/api/opportunities/stage-limits").json()["custom"] == []
    assert login_as(client, RAVI).get("/api/leads/stage-limits").json()["custom"] == ["New"]
    log = login_as(client, ASHA).get("/api/activity-log").json()
    assert any(r["action"] == "Lead In stage limits changed" and r["target"] == "Leads" for r in log)
    assert limits_put(client, ASHA, {"New": None}).json()["custom"] == []
    assert clock(client, lead)["category"] == "attention"


@pytest.mark.parametrize("limits, status", [
    ({"New": [-1, 5]}, 400), ({"New": [5, 5]}, 400), ({"Demo": [6, 5]}, 400), ({"New": [1, 366]}, 400),
    ({"Converted": [1, 2]}, 400), ({"Proposal": [1, 2]}, 400), ({"New": [1.5, 3]}, 422), ({"New": ["1", "3"]}, 422),
])
def test_lead_limits_are_whole_days_attention_below_stalled_for_rated_statuses(client, limits, status):
    assert limits_put(client, ASHA, limits).status_code == status
    for user in (PRIYA, RAVI):
        assert limits_put(client, user, {"New": [1, 2]}).status_code == 403
    assert login_as(client, ASHA).get("/api/leads/stage-limits").json()["custom"] == []


def test_pooled_waiting_time_is_never_stalled_whatever_the_limits(client, team):
    upload(login_as(client, ASHA), pool_rows(1))
    [pooled] = pooled_ids(client)
    set_times(pooled, created=ago(days=40))
    limits_put(client, ASHA, {"New": [0, 1]})
    c = clock(client, pooled)
    assert (c["state"], c["category"]) == ("unassigned", None)
    assert page(client, with_stalled="true", owner="unassigned")["stalled"] == 0
    # an In stage choice on the pool alone matches nothing (answered without every lead's clock: it was minutes at 50,000)
    for params in ({"owner": "unassigned"}, {"view": "unassigned"}):
        assert page(client, in_stage="stalled", sort="in_stage", **params)["total"] == 0
    assert page(client, view="unassigned", sort="in_stage")["total"] == 1


# ---------- 4. Owner: several people and the Unassigned Pool; the Stalled count ----------

def test_owner_takes_several_people_and_the_pool_within_the_users_access_and_stalled_counts_before_paging(client, team):
    ravis = own_lead(client, RAVI, "Rana")
    priyas = own_lead(client, PRIYA, "Prem")
    upload(login_as(client, ASHA), pool_rows(1))
    [pooled] = pooled_ids(client)
    ids = lambda **p: sorted(x["id"] for x in page(client, **p)["items"])  # noqa: E731
    assert ids(owner=f"{PRIYA},unassigned") == sorted([priyas, pooled])  # any of them (the Admin sees all)
    assert ids(owner=f"{RAVI},{PRIYA}") == sorted([ravis, priyas])
    # a Salesperson without team access: naming others never widens their list
    own = sorted(x["id"] for x in page(client, RAVI, owner=f"{RAVI},{PRIYA}")["items"])
    assert own == [ravis]
    assert login_as(client, ASHA).get("/api/leads/page", params={"owner": "2;1"}).status_code == 400
    # the Stalled count: every other filter, In stage left out; one page or many, the same number
    set_times(ravis, created=ago(days=9))  # New for 9 days: stalled
    set_times(priyas, created=ago(days=9))  # Priya is a Manager: her own lead isn't timed (not a Salesperson's)
    first = page(client, with_stalled="true", limit=1)
    assert first["stalled"] == 1 and len(first["items"]) == 1
    assert page(client, with_stalled="true", owner=str(PRIYA))["stalled"] == 0
    assert page(client, with_stalled="true", in_stage="on_track")["stalled"] == 1  # its own filter left out


# ---------- 3. saved Leads views: Update View, kept apart from Opportunities views ----------

LEAD_FILTERS = {"owner": f"{RAVI},unassigned", "stage": "New", "source": "Upload", "region": "in",
                "in_stage": "stalled", "created": "lastweek"}


def test_a_leads_view_is_saved_updated_renamed_and_kept_apart_from_opportunities_views(client):
    login_as(client, PRIYA)
    res = client.post("/api/saved-views", json={"collection": "leads", "name": "Stalled pool", "base_view": "All Open Leads",
                                                "filters": LEAD_FILTERS, "search": "acme",
                                                "sort": {"column": "in_stage", "dir": "desc"}})
    assert res.status_code == 201, res.text
    view = res.json()
    assert view["filters"] == {**LEAD_FILTERS, "region": "IN"} and view["sort"] == {"column": "in_stage", "dir": "desc"}
    opp = client.post("/api/saved-views", json={"collection": "opportunities", "name": "Stalled pool",
                                                "base_view": "All Opportunities"})
    assert opp.status_code == 201  # the same name on the other list is fine: they are separate
    # Update View: the list's current filters, search and sort replace the saved ones
    updated = client.patch(f"/api/saved-views/{view['id']}", json={
        "collection": "leads", "filters": {"stage": "Demo", "modified": "lastmonth"}, "search": "",
        "sort": {"column": "name", "dir": "asc"}})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["filters"], body["search"], body["sort"], body["name"], body["base_view"]) == (
        {"stage": "Demo", "modified": "lastmonth"}, "", {"column": "name", "dir": "asc"}, "Stalled pool", "All Open Leads")
    # never across lists: an Opportunities update or delete can't touch a Leads view (nor the other way round)
    assert client.patch(f"/api/saved-views/{view['id']}", json={"collection": "opportunities", "filters": {}}).status_code == 404
    assert client.delete(f"/api/saved-views/{opp.json()['id']}", params={"collection": "leads"}).status_code == 404
    assert [v["name"] for v in client.get("/api/saved-views", params={"collection": "opportunities"}).json()] == ["Stalled pool"]
    assert client.get("/api/saved-views", params={"collection": "leads"}).json()[0]["filters"]["stage"] == "Demo"
    # someone else's view can't be updated
    assert login_as(client, ASHA).patch(f"/api/saved-views/{view['id']}", json={"filters": {}}).status_code == 404
    # an Opportunities filter on a Leads view (and the other way round) is refused
    for collection, filters in (("leads", {"currency": "INR"}), ("opportunities", {"region": "IN"}),
                                ("opportunities", {"owner": "unassigned"})):
        target = view["id"] if collection == "leads" else opp.json()["id"]
        res = login_as(client, PRIYA).patch(f"/api/saved-views/{target}", json={"collection": collection, "filters": filters})
        assert res.status_code == 400, (collection, filters)


@pytest.mark.parametrize("filters, base", [
    ({"region": "ZZ"}, "All Leads"), ({"created": "month"}, "All Leads"), ({"stage": "Proposal"}, "All Leads"),
    ({"owner": "unassigned"}, "My Leads"), ({"owner": str(PRIYA)}, "All Leads"), ({}, "Deleted Leads"),
])
def test_leads_view_values_and_owners_are_checked(client, filters, base):
    res = login_as(client, RAVI).post("/api/saved-views", json={"collection": "leads", "name": "Checked",
                                                                 "base_view": base, "filters": filters})
    assert res.status_code == 400, res.text


def test_a_salesperson_may_name_themselves_and_the_unassigned_pool(client):
    res = login_as(client, RAVI).post("/api/saved-views", json={"collection": "leads", "name": "Mine and pool",
                                                                 "base_view": "All Open Leads",
                                                                 "filters": {"owner": f"{RAVI},unassigned"}})
    assert res.status_code == 201 and res.json()["filters"]["owner"] == f"{RAVI},unassigned"
