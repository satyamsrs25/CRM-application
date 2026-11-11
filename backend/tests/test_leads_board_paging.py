"""Leads Kanban paging on a large synthetic set (549 leads, more than 100 in two stages), in the throwaway test
database: every column's page comes from GET /api/leads/page (stage, offset, limit), so every lead can be reached past
the old first 100 cards, totals are exact, pages never overlap, and access rules and filters still apply.
All data is made up."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import insert

from app.database import get_db
from app.main import app
from app.models import Lead
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin (conftest.py)
# 549 leads: Nurturing and Demo have more than 100 cards each (the old board stopped at 100)
PLAN = {"New": 200, "Nurturing": 120, "Revisit": 40, "Demo": 105, "Unqualified": 30, "Lost": 54}
OPEN = ["New", "Nurturing", "Revisit", "Demo"]
START = datetime(2026, 1, 1, 9, 0)


@pytest.fixture
def board(client):
    """Inserts the 549 leads directly (fast); every third one is Priya's, the rest Ravi's; every fifth is an upload."""
    db = next(app.dependency_overrides[get_db]())
    rows, n = [], 0
    for stage, count in PLAN.items():
        for i in range(count):
            n += 1
            rows.append({"first_name": "Synthetic", "last_name": f"Board {n:03d}", "company": f"Kanban Paging Co {n:03d}",
                         "email": f"board{n:03d}@kanban-paging.example", "stage": stage,
                         "source": "Upload" if n % 5 == 0 else "Website", "owner_id": PRIYA if n % 3 == 0 else RAVI,
                         "created_at": START + timedelta(minutes=n), "updated_at": START + timedelta(minutes=n)})
    db.execute(insert(Lead), rows)
    db.commit()
    db.close()
    assert sum(PLAN.values()) == 549
    return rows


def column(client, stage, offset, limit, **params):
    res = client.get("/api/leads/page", params={"view": "all", "stage": stage, "offset": offset, "limit": limit, **params})
    assert res.status_code == 200, res.text
    return res.json()


def walk(client, stage, limit, **params):
    """Next, Next, Next... through one column: every page's leads, and the total each page reported."""
    seen, totals, offset = [], set(), 0
    while True:
        page = column(client, stage, offset, limit, **params)
        totals.add(page["total"])
        seen += [lead["id"] for lead in page["items"]]
        if offset + limit >= page["total"]:
            return seen, totals
        offset += limit


@pytest.mark.parametrize("limit", [15, 25, 50, 100])  # the List page's choices of cards per page
def test_every_card_of_every_column_can_be_reached(client, board, limit):
    login_as(client, PRIYA)  # a Manager sees the team's leads
    for stage, count in PLAN.items():
        ids, totals = walk(client, stage, limit)
        assert totals == {count}, stage            # the same exact total on every page
        assert len(ids) == len(set(ids)) == count  # no lead twice, none missing (past 100 too)


def test_the_101st_card_and_the_last_page(client, board):
    login_as(client, PRIYA)
    first_100 = column(client, "Nurturing", 0, 100)
    rest = column(client, "Nurturing", 100, 100)
    assert first_100["total"] == rest["total"] == 120
    assert len(first_100["items"]) == 100 and len(rest["items"]) == 20
    assert not {l["id"] for l in first_100["items"]} & {l["id"] for l in rest["items"]}
    # a page past the end (after cards moved out) is empty with the real total, so the board goes back a page
    past = column(client, "Demo", 105, 15)
    assert past["total"] == 105 and past["items"] == []


def test_pages_follow_the_sort_without_gaps(client, board):
    login_as(client, PRIYA)
    for sort, direction in (("name", "asc"), ("company", "desc"), ("created", "asc"), ("owner", "asc")):
        ids, _ = walk(client, "New", 25, sort=sort, direction=direction)
        assert len(ids) == len(set(ids)) == 200, sort
    names = [l["name"] for l in column(client, "Demo", 0, 15, sort="name", direction="asc")["items"]]
    assert names == sorted(names)


def test_filters_and_search_give_exact_column_totals(client, board):
    login_as(client, PRIYA)
    def expected(stage, test):
        return sum(1 for r in board if r["stage"] == stage and test(r))
    for stage in OPEN:
        assert column(client, stage, 0, 15, source="Upload")["total"] == expected(stage, lambda r: r["source"] == "Upload")
        assert column(client, stage, 0, 15, owner=str(RAVI))["total"] == expected(stage, lambda r: r["owner_id"] == RAVI)
    # Created: a date range (the board sends the same from/to as the List page)
    window = {"created_from": (START + timedelta(minutes=201)).isoformat(),
              "created_to": (START + timedelta(minutes=261)).isoformat()}
    assert column(client, "Nurturing", 0, 100, **window)["total"] == 60
    assert column(client, "Nurturing", 0, 15, search="Paging Co 2")["total"] == expected(
        "Nurturing", lambda r: "Paging Co 2" in r["company"])
    # the list view decides which columns have leads at all (All Open Leads has no Lost or Unqualified)
    assert column(client, "Lost", 0, 15, view="all_open")["total"] == 0


def test_columns_count_only_the_leads_the_user_may_see(client, board):
    login_as(client, RAVI)  # a Salesperson without team access sees only their own leads
    for stage, count in PLAN.items():
        mine = sum(1 for r in board if r["stage"] == stage and r["owner_id"] == RAVI)
        ids, totals = walk(client, stage, 50)
        assert totals == {mine} and len(set(ids)) == mine
    assert login_as(client, PRIYA).put(f"/api/users/{RAVI}/team-access", json={"team_access": True}).status_code == 200
    login_as(client, RAVI)
    assert column(client, "Demo", 0, 15)["total"] == PLAN["Demo"]  # team access: the whole team's leads
