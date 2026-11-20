"""The Leads list's Region filter (GET /api/leads/page?region=) and Assign for the ticked pooled leads
(POST /api/leads/bulk-assign).

Users: 1 Priya (Manager: Ravi and Tara report to her), 2 Ravi (Salesperson), 3 Asha (Admin); the `team` fixture adds
Tara (Priya's team), Mona (Manager) with Sam, and Leo (no Manager). All leads and people are made up."""
import csv
import io

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models import ActivityLog, Lead, LeadTransfer, LeadTransferRequest
from app.routers import leads as leads_router
from conftest import login_as
from test_unassigned_pool import ASHA, PRIYA, RAVI, REASON, bell, db, lead_row, outbox, team, without  # noqa: F401


def upload(client, rows, name="regions.csv"):
    """Pooled leads from a file (the Admin uploads): rows of (first name, email, Region (Country) or "")."""
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Company", "Email", "Lead Source", "Region (Country)"],
                               *[[first, "Region Filter Synthetic", email, "Website", region] for first, email, region in rows]])
    res = login_as(client, ASHA).post("/api/leads/import", files={"file": (name, out.getvalue().encode(), "text/csv")},
                                      data={"dry_run": "false"})
    assert res.status_code == 200 and res.json()["created"] == len(rows), res.text
    with db() as s:
        return {l.email: l.id for l in s.query(Lead).filter(Lead.email.in_([r[1] for r in rows]))}


def own(client, user_id, first, region=None, **extra):
    body = {"first_name": first, "company": "Own Region Synthetic", "source": "Website",
            "email": f"{first.lower()}@own-region.example", **({"phone_country": region} if region else {}), **extra}
    res = login_as(client, user_id).request("POST", "/api/leads", json=body)  # no default phone
    assert res.status_code == 201, res.text
    return res.json()["id"]


def page(client, user_id, **params):
    res = login_as(client, user_id).get("/api/leads/page", params={"limit": 500, **params})
    assert res.status_code == 200, res.text
    return res.json()


def ids(body):
    return sorted(l["id"] for l in body["items"])


# ---------- Region filter ----------

@pytest.fixture
def mixed(client):
    """7 pooled leads (3 India, 2 United States, 2 none) and Ravi's own (India, Canada, none)."""
    pooled = upload(client, [("Pa", "pa@region-filter.example", "India"), ("Pb", "pb@region-filter.example", "IN"),
                             ("Pc", "pc@region-filter.example", "+91"), ("Pd", "pd@region-filter.example", "US"),
                             ("Pe", "pe@region-filter.example", "United States"), ("Pf", "pf@region-filter.example", ""),
                             ("Pg", "pg@region-filter.example", "")])
    mine = {"in": own(client, RAVI, "Ria", "IN"), "ca": own(client, RAVI, "Cal", "CA"), "none": own(client, RAVI, "Nob")}
    by = lambda *emails: sorted(pooled[f"{e}@region-filter.example"] for e in emails)  # noqa: E731
    return {"pool_in": by("pa", "pb", "pc"), "pool_us": by("pd", "pe"), "pool_none": by("pf", "pg"), "mine": mine}


def test_the_region_filter_counts_the_whole_list_before_paging(client, mixed):
    india = sorted([*mixed["pool_in"], mixed["mine"]["in"]])
    full = page(client, ASHA, view="all_open", region="IN")
    assert (full["total"], ids(full)) == (4, india)
    seen = []
    for offset in (0, 3):  # every page of the filtered list, once
        one = page(client, ASHA, view="all_open", region="IN", limit=3, offset=offset)
        assert one["total"] == 4 and all(l["phone_country"] == "IN" for l in one["items"])
        seen += ids(one)
    assert sorted(seen) == india
    # Not specified: leads without a Region (an older lead with none counts too: nothing is guessed for it)
    with db() as s:
        old = Lead(first_name="Old", last_name="Lead", company="Older Synthetic", source="Website", stage="New",
                   owner_id=RAVI, phone="+91 98765 43210")
        s.add(old)
        s.commit()
        old_id = old.id
    none = page(client, ASHA, view="all_open", region="none")
    assert ids(none) == sorted([*mixed["pool_none"], mixed["mine"]["none"], old_id])
    assert lead_row(old_id).phone_country is None  # still empty
    assert page(client, ASHA, view="all_open", region="ca")["total"] == 1  # a code in any case
    assert login_as(client, ASHA).get("/api/leads/page", params={"region": "ZZ"}).status_code == 400


def test_the_region_filter_combines_with_views_search_and_other_filters(client, mixed):
    assert ids(page(client, ASHA, view="unassigned", region="IN")) == mixed["pool_in"]
    assert ids(page(client, ASHA, view="uploaded", region="US")) == mixed["pool_us"]
    assert ids(page(client, ASHA, view="all_open", region="IN", owner=str(RAVI))) == [mixed["mine"]["in"]]
    assert ids(page(client, ASHA, view="all_open", region="IN", owner="unassigned")) == mixed["pool_in"]
    assert ids(page(client, ASHA, view="all_open", region="IN", search="Ria")) == [mixed["mine"]["in"]]
    assert page(client, ASHA, view="all_open", region="CA", source="Upload")["total"] == 0
    # the Kanban asks the same list per column: Unassigned + the stage columns (assigned leads) = the List's total
    pool_col = page(client, ASHA, view="all_open", region="IN", owner="unassigned")["total"]
    stage_cols = sum(page(client, ASHA, view="all_open", region="IN", stage=s, assigned="true")["total"]
                     for s in ("New", "Nurturing", "Revisit", "Demo"))
    assert (pool_col, stage_cols, page(client, ASHA, view="all_open", region="IN")["total"]) == (3, 1, 4)


def test_a_salesperson_sees_and_filters_pooled_leads_by_region(client, mixed):
    """Ravi (a Salesperson) may list the Unassigned Pool but only request its leads: their Region (the country) is shown
    and filtered like his own leads', while their email, phone and LinkedIn stay hidden (and unsearchable), as before."""
    everything = page(client, RAVI, view="all_open")
    pool = {l["id"]: l for l in everything["items"] if l["in_pool"]}
    assert len(pool) == 7
    assert {pool[i]["region"] for i in mixed["pool_in"]} == {"India"}
    assert {pool[i]["phone_country"] for i in mixed["pool_us"]} == {"US"}
    assert all((l["contact_hidden"], l["email"], l["phone"], l["linkedin_url"]) == (True, None, None, None)
               for l in pool.values())
    assert ids(page(client, RAVI, view="all_open", region="IN")) == sorted([*mixed["pool_in"], mixed["mine"]["in"]])
    assert ids(page(client, RAVI, view="all_open", region="none")) == sorted([*mixed["pool_none"], mixed["mine"]["none"]])
    assert ids(page(client, RAVI, view="unassigned", region="US")) == mixed["pool_us"]
    assert ids(page(client, RAVI, view="my_open", region="IN")) == [mixed["mine"]["in"]]  # his own view: his own only
    # a country no lead has: the normal empty list (a valid choice, not an error)
    assert page(client, RAVI, view="all_open", region="FR") == {"total": 0, "offset": 0, "limit": 500, "items": []}
    # the hidden contact details still aren't searchable on pooled leads, with or without a Region
    assert page(client, RAVI, view="all_open", region="IN", search="pa@region-filter")["total"] == 0
    found = page(client, ASHA, view="all_open", region="IN", search="pa@region-filter")  # the Admin may search them
    assert found["total"] == 1 and found["items"][0]["id"] in mixed["pool_in"]


def test_a_manager_sees_their_teams_regions_and_the_pools(client, team, mixed):
    tara_us = own(client, team["tara"], "Tia", "US")
    sams = own(client, team["sam"], "Sid", "JM")  # Mona's team
    priya = page(client, PRIYA, view="all_open", region="US")
    assert ids(priya) == sorted([*mixed["pool_us"], tara_us])  # the pool's too: she may assign it
    assert page(client, PRIYA, view="my_open", region="US")["total"] == 0  # My Open Leads: her own (none)
    assert sams not in ids(page(client, team["mona"], view="all_open", region="IN"))


# ---------- Assign for the ticked pooled leads ----------

def assign(client, user_id, lead_ids, to, note=None):
    return login_as(client, user_id).post("/api/leads/bulk-assign", json={"lead_ids": lead_ids, "to_user_id": to, "note": note})


def counts():
    with db() as s:
        return s.query(LeadTransfer).count(), s.query(ActivityLog).count()


def test_the_admin_assigns_the_ticked_pooled_leads_with_history_and_one_summary(client, team, outbox, mixed):
    targets = mixed["pool_in"]
    asked = login_as(client, team["tara"]).post("/api/transfer-requests/bulk", json={"lead_ids": [targets[0]], "reason": REASON})
    assert asked.json()["requested"] == 1
    ravi_bell, tara_bell = len(bell(RAVI)), len(bell(team["tara"]))
    outbox.clear()
    res = assign(client, ASHA, targets, RAVI, note="Synthetic: your territory")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["assigned"], body["to"], body["conflicts"], body["skipped"], body["failed"]) == (3, "Ravi Kumar", [], [], [])
    with db() as s:
        rows = {l.id: l for l in s.query(Lead).filter(Lead.id.in_(targets))}
        assert all(l.owner_id == RAVI and l.assigned_at is not None and l.stage == "New" and l.created_by_id == ASHA
                   for l in rows.values())
        history = {t.lead_id: (t.from_user_id, t.to_user_id, t.transferred_by_id, t.note) for t in s.query(LeadTransfer)}
        request = s.query(LeadTransferRequest).one()
    assert history == {i: (None, RAVI, ASHA, "Synthetic: your territory") for i in targets}
    assert (request.status, request.decision_note) == ("Rejected", "The lead was assigned to Ravi Kumar")
    # Ravi: one summary for the batch (bell and email); Tara: her request was closed, told once
    assert [t for t, _ in bell(RAVI)[ravi_bell:]] == ["Leads assigned to you"]
    assert "assigned you 3 leads from the Unassigned Pool" in bell(RAVI)[-1][1]
    assert [t for t, _ in bell(team["tara"])[tara_bell:]] == ["Lead request closed"]
    assert sorted(m["to"][0] for m in outbox) == ["ravi@crm.test", "tara@crm.test"]


def test_a_manager_assigns_only_to_their_own_salespeople(client, team, mixed):
    lead = mixed["pool_us"][0]
    refused = assign(client, PRIYA, [lead], team["sam"])  # Sam reports to Mona
    assert refused.status_code == 403 and "who report to you" in refused.json()["detail"]
    assert lead_row(lead).owner_id is None
    assert assign(client, team["mona"], [lead], team["tara"]).status_code == 403  # an unrelated Manager
    assert assign(client, PRIYA, [lead], team["tara"]).json()["assigned"] == 1
    assert assign(client, team["mona"], [mixed["pool_us"][1]], team["sam"]).json()["assigned"] == 1


def test_salespeople_and_managers_without_reassign_owner_cant_assign(client, team, mixed):
    lead = mixed["pool_none"][0]
    res = assign(client, RAVI, [lead], RAVI)
    assert res.status_code == 403 and "You can request these leads instead." in res.json()["detail"]
    without("Manager", "reassign_owner")
    assert assign(client, PRIYA, [lead], team["tara"]).status_code == 403
    assert lead_row(lead).owner_id is None


def test_owned_leads_in_the_selection_are_never_reassigned(client, team, mixed):
    owned = mixed["mine"]["in"]  # Ravi's own lead, ticked beside pooled ones
    body = assign(client, ASHA, [owned, *mixed["pool_us"]], team["tara"]).json()
    assert [d["id"] for d in body["done"]] == mixed["pool_us"]
    assert [(c["id"], c["reason"]) for c in body["conflicts"]] == [
        (owned, "Not in the Unassigned Pool any more: it belongs to Ravi Kumar")]
    assert lead_row(owned).owner_id == RAVI


def test_a_lead_assigned_meanwhile_keeps_its_new_owner(client, team, mixed):
    first, second = mixed["pool_in"][:2]
    # someone else assigns one of the ticked leads first (the single Assign)
    assert login_as(client, PRIYA).post(f"/api/leads/{first}/assign", json={"to_user_id": team["tara"]}).status_code == 200
    before = counts()
    body = assign(client, ASHA, [first, second], RAVI).json()
    assert [d["id"] for d in body["done"]] == [second]
    assert body["conflicts"][0]["reason"] == "Not in the Unassigned Pool any more: it belongs to Tara Nair"
    assert (lead_row(first).owner_id, lead_row(second).owner_id) == (team["tara"], RAVI)
    assert counts()[0] == before[0] + 1  # one new Transfer History record: the lead that was assigned
    # sent again (a second click): nothing is assigned twice and nobody is told again
    ravi_bell = len(bell(RAVI))
    again = assign(client, ASHA, [first, second], RAVI).json()
    assert (again["assigned"], len(again["conflicts"])) == (0, 2) and len(bell(RAVI)) == ravi_bell


def test_closed_missing_and_failing_leads_are_reported_and_the_rest_assigned(client, team, mixed, monkeypatch):
    with db() as s:
        lost = Lead(first_name="Gone", last_name="Pool", company="Closed Synthetic", source="Upload", stage="Lost",
                    lost_reason="Price", owner_id=None)
        s.add(lost)
        s.commit()
        lost_id = lost.id
    breaks = mixed["pool_none"][1]
    real = leads_router.assign_from_pool

    def flaky(db_, lead, *args, **kwargs):
        if lead.id == breaks:
            raise SQLAlchemyError("synthetic database failure")
        return real(db_, lead, *args, **kwargs)

    monkeypatch.setattr(leads_router, "assign_from_pool", flaky)
    body = assign(client, ASHA, [lost_id, 999999, breaks, mixed["pool_none"][0]], RAVI).json()
    assert [d["id"] for d in body["done"]] == [mixed["pool_none"][0]]
    assert {s["id"]: s["reason"] for s in body["skipped"]} == {
        lost_id: f"Lead {lost_id} is Lost (closed); it can't change any more", 999999: "Lead 999999 not found"}
    assert body["failed"] == [{"id": breaks, "name": lead_row(breaks).name, "reason": "It couldn't be saved. Try again."}]
    assert (lead_row(lost_id).owner_id, lead_row(breaks).owner_id) == (None, None)  # nothing saved for them


@pytest.mark.parametrize("lead_ids", [[], list(range(1, 502))])
def test_assign_takes_one_to_500_leads(client, lead_ids):
    assert assign(client, ASHA, lead_ids, RAVI).status_code == 422


def test_the_target_must_be_an_active_salesperson(client, team, mixed):
    lead = mixed["pool_in"][0]
    for target in (PRIYA, ASHA, 999999):
        assert assign(client, ASHA, [lead], target).status_code == 400
    assert lead_row(lead).owner_id is None
