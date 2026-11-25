"""Saved list views (app/routers/saved_views.py): Opportunities > Save as View. Each user keeps their own named views
(their filters, search and sort, with dates kept as choices so they stay dynamic); nobody else can see, rename or delete
them; names and filter values are checked; and the owners a view names are checked against the user's access when it
is saved and again whenever it is read.

Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin). All data is made up."""
import pytest

from app.models import User
from conftest import login_as
from test_unassigned_pool import ASHA, PRIYA, RAVI, db  # noqa: F401

URL = "/api/saved-views"
FULL = {"stage": "Proposal", "in_stage": "stalled", "currency": "INR", "overdue_stuck": "1", "close": "month",
        "created": "custom", "created_from": "2026-11-01", "created_to": "2026-11-30", "modified": "last30"}


def save(client, user_id, name="Synthetic view", base="All Opportunities", filters=None, **extra):
    body = {"collection": "opportunities", "name": name, "base_view": base, "filters": filters or {}, **extra}
    return login_as(client, user_id).post(URL, json=body)


def views(client, user_id):
    res = login_as(client, user_id).get(URL, params={"collection": "opportunities"})
    assert res.status_code == 200, res.text
    return {v["name"]: v for v in res.json()}


def set_team_access(user_id, value):
    with db() as s:
        s.get(User, user_id).team_access = value
        s.commit()


def test_a_view_keeps_its_choices_search_and_sort_and_dates_stay_dynamic(client):
    res = save(client, RAVI, "Late INR proposals", "My Open Opportunities", FULL, search=" acme ",
               sort={"column": "Amount", "dir": -1})
    assert res.status_code == 201, res.text
    saved = views(client, RAVI)["Late INR proposals"]
    assert saved["filters"] == FULL  # "month" stays This month: worked out each time, never a fixed date
    assert (saved["base_view"], saved["search"], saved["sort"], saved["adjusted"]) == (
        "My Open Opportunities", "acme", {"column": "Amount", "dir": -1}, False)
    # no sort given: the list's default
    assert save(client, RAVI, "Plain").json()["sort"] == {"column": "Opportunity Name", "dir": 1}


def test_only_the_owner_sees_renames_or_deletes_a_view(client):
    mine = save(client, RAVI, "Ravi only").json()
    assert save(client, PRIYA, "Priya only").status_code == 201
    assert list(views(client, RAVI)) == ["Ravi only"]
    assert list(views(client, PRIYA)) == ["Priya only"]
    for user in (PRIYA, ASHA):  # not even the Manager or the Admin
        assert login_as(client, user).patch(f"{URL}/{mine['id']}", json={"name": "Taken over"}).status_code == 404
        assert login_as(client, user).delete(f"{URL}/{mine['id']}").status_code == 404
    renamed = login_as(client, RAVI).patch(f"{URL}/{mine['id']}", json={"name": "  Ravi   renamed "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ravi renamed"
    deleted = login_as(client, RAVI).delete(f"{URL}/{mine['id']}")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": mine["id"]}  # JSON, like every API here
    assert views(client, RAVI) == {} and list(views(client, PRIYA)) == ["Priya only"]


@pytest.mark.parametrize("name, detail", [
    ("   ", "Enter a name"), ("x" * 61, "up to 60"), ("All Opportunities", "standard view"),
    ("my open opportunities", "standard view"), ("Bad <b>", "can't contain"), ("ravi's view", "already have"),
])
def test_names_are_checked(client, name, detail):
    assert save(client, RAVI, "Ravi's View").status_code == 201
    res = save(client, RAVI, name)
    assert res.status_code == 400 and detail in res.json()["detail"], res.text


@pytest.mark.parametrize("filters, extra", [
    ({"stage": "Closed"}, {}), ({"in_stage": "late"}, {}), ({"currency": "GBP"}, {}), ({"overdue_stuck": "yes"}, {}),
    ({"close": "next90"}, {}), ({"created": "overdue"}, {}), ({"close": "custom"}, {}),
    ({"close": "custom", "close_from": "2026-13-01"}, {}),
    ({"close": "custom", "close_from": "2026-12-01", "close_to": "2026-11-01"}, {}),
    ({"close_from": "2026-11-01"}, {}), ({"password": "x"}, {}), ({"owner": "2;DROP"}, {}),
    ({}, {"sort": {"column": "password_hash", "dir": 1}}), ({}, {"sort": {"column": "Amount", "dir": 2}}),
    ({}, {"base_view": "Everyone's Opportunities"}), ({}, {"collection": "leads"}),
])
def test_filter_values_sort_base_view_and_list_are_checked(client, filters, extra):
    body = {"collection": "opportunities", "name": "Checked", "base_view": "All Opportunities", "filters": filters,
            **extra}
    res = login_as(client, PRIYA).post(URL, json=body)
    assert res.status_code == 400, res.text
    assert views(client, PRIYA) == {}


def test_owner_choices_follow_the_users_access_when_saved_and_when_read(client):
    # a Salesperson who sees only their own opportunities can choose only themselves
    refused = save(client, RAVI, "Priya's deals", filters={"owner": str(PRIYA)})
    assert refused.status_code == 400 and "whose opportunities you can see" in refused.json()["detail"]
    assert save(client, RAVI, "Mine", filters={"owner": str(RAVI)}).status_code == 201
    # "My ..." views are the user's own already: no Owner filter on them
    assert save(client, PRIYA, "My pair", "My Opportunities", {"owner": f"{PRIYA},{RAVI}"}).status_code == 400
    # the Manager and the Admin (team records) choose anyone; unknown people are refused
    assert save(client, PRIYA, "Team pair", filters={"owner": f"{RAVI},{ASHA}"}).status_code == 201
    assert save(client, ASHA, "Ghost", filters={"owner": "999"}).status_code == 400
    # team access given by a Manager widens the choice; taken away, the view keeps only what is still allowed
    set_team_access(RAVI, True)
    assert save(client, RAVI, "Team view", filters={"owner": f"{PRIYA},{RAVI}", "stage": "Proposal"}).status_code == 201
    set_team_access(RAVI, False)
    team_view = views(client, RAVI)["Team view"]
    assert team_view["filters"] == {"owner": str(RAVI), "stage": "Proposal"} and team_view["adjusted"] is True
    assert views(client, RAVI)["Mine"]["adjusted"] is False
    # and the records are still only what the list allows (a view never fetches anything itself)
    assert all(o["owner_id"] == RAVI for o in login_as(client, RAVI).get("/api/opportunities").json())


def test_a_user_keeps_at_most_fifty_views(client):
    for i in range(50):
        assert save(client, RAVI, f"View {i}").status_code == 201
    res = save(client, RAVI, "One too many")
    assert res.status_code == 400 and "up to 50 views" in res.json()["detail"]
