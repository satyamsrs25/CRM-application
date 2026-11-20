"""Vinay's improvements 1 and 2: To Approve's Approve Selected / Reject Selected (POST /api/transfer-requests/bulk-decision)
and its Requested By filter (GET /api/transfer-requests/page).

Users: 1 Priya (Manager: Ravi and Tara report to her), 2 Ravi (Salesperson), 3 Asha (Admin); the `team` fixture adds
Tara (Priya's team), Mona (Manager) with Sam, and Leo (no Manager). All leads and people are made up."""
import pytest

from app.models import ActivityLog, Lead, LeadTransfer, LeadTransferRequest, User
from conftest import login_as
from test_unassigned_pool import (ASHA, PRIYA, RAVI, REASON, bell, db, lead_row, outbox, pool_rows,  # noqa: F401
                                  pooled_ids, team, upload)

BULK = "/api/transfer-requests/bulk-decision"


def pooled(client, n, prefix):
    upload(login_as(client, ASHA), pool_rows(n, prefix=prefix))
    return sorted(i for i in pooled_ids(client) if lead_row(i).last_name.startswith(prefix))


def ask(client, user_id, lead_ids):
    res = login_as(client, user_id).post("/api/transfer-requests/bulk", json={"lead_ids": lead_ids, "reason": REASON})
    assert res.status_code == 200 and res.json()["requested"] == len(lead_ids), res.text
    return [c["id"] for c in res.json()["created"]]


def decide(client, user_id, decision, ids, note=None):
    return login_as(client, user_id).post(BULK, json={"decision": decision, "request_ids": ids, "note": note})


def request_row(request_id) -> LeadTransferRequest:
    with db() as s:
        row = s.get(LeadTransferRequest, request_id)
        s.expunge(row)
        return row


def counts():
    with db() as s:
        return (s.query(LeadTransfer).count(), s.query(ActivityLog).count(),
                {r.id: r.status for r in s.query(LeadTransferRequest)})


# ---------- Approve Selected / Reject Selected ----------

def test_the_admin_approves_only_the_selected_requests_each_with_its_own_history_and_notice(client, team, outbox):
    leads = pooled(client, 4, "Bulk")
    ravis = ask(client, RAVI, leads[:2])
    tara, sam = ask(client, team["tara"], [leads[2]]), ask(client, team["sam"], [leads[3]])
    ravi_bell, sam_bell = len(bell(RAVI)), len(bell(team["sam"]))
    outbox.clear()
    res = decide(client, ASHA, "approve", [*ravis, *tara], note="Synthetic: approved together")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["approved"], body["conflicts"], body["skipped"]) == (3, [], [])
    assert {d["id"] for d in body["done"]} == {*ravis, *tara} and all(d["status"] == "Approved" for d in body["done"])
    # each lead went to its requester, with its own transfer record naming its request
    assert [lead_row(i).owner_id for i in leads] == [RAVI, RAVI, team["tara"], None]
    with db() as s:
        transfers = {t.lead_id: t.request_id for t in s.query(LeadTransfer)}
        logs = [a.action for a in s.query(ActivityLog).filter(ActivityLog.action == "Lead request approved")]
    assert transfers == {leads[0]: ravis[0], leads[1]: ravis[1], leads[2]: tara[0]}
    assert len(logs) == 3  # one Activity Log line per request, as when deciding one
    for request_id in [*ravis, *tara]:
        row = request_row(request_id)
        assert (row.status, row.decided_by_id, row.decision_note) == ("Approved", ASHA, "Synthetic: approved together")
    # the requester hears about each request once (as for single approvals); Sam's request wasn't selected
    assert [t for t, _ in bell(RAVI)[ravi_bell:]] == ["Lead assigned to you", "Lead assigned to you"]
    assert len(bell(team["sam"])) == sam_bell and request_row(sam[0]).status == "Pending"
    assert sorted(m["to"][0] for m in outbox) == sorted(["ravi@crm.test", "ravi@crm.test", "tara@crm.test"])


def test_a_manager_decides_only_their_own_teams_requests(client, team):
    leads = pooled(client, 2, "Team")
    ravi, sam = ask(client, RAVI, [leads[0]])[0], ask(client, team["sam"], [leads[1]])[0]
    sam_bell = len(bell(team["sam"]))
    body = decide(client, PRIYA, "approve", [ravi, sam]).json()
    assert [d["id"] for d in body["done"]] == [ravi]
    assert [(s["id"], s["reason"]) for s in body["skipped"]] == [
        (sam, "Only the Admin, or the Manager the requester reports to (with Reassign owner), can approve this")]
    assert (lead_row(leads[1]).owner_id, request_row(sam).status) == (None, "Pending")  # nothing changed for Sam
    assert len(bell(team["sam"])) == sam_bell  # and nobody told him anything
    # Mona (Sam's Manager) can; the Admin could too
    assert decide(client, team["mona"], "approve", [sam]).json()["approved"] == 1


def test_a_salesperson_cant_decide_in_bulk_but_still_decides_one_at_a_time(client, team):
    owned = login_as(client, RAVI).post("/api/leads", json={"first_name": "Rita", "last_name": "Owned",
                                                             "company": "Owned Synthetic Co", "source": "Website",
                                                             "email": "rita@owned-synthetic.example"}).json()
    asked = login_as(client, team["tara"]).post(f"/api/leads/{owned['id']}/transfer-requests", json={"reason": REASON})
    assert asked.status_code == 201, asked.text
    request_id = asked.json()["id"]
    res = decide(client, RAVI, "approve", [request_id])
    assert res.status_code == 403 and "Only the Admin or a Manager" in res.json()["detail"]
    assert request_row(request_id).status == "Pending"
    single = login_as(client, RAVI).post(f"/api/transfer-requests/{request_id}/approve", json={})
    assert single.status_code == 200 and single.json()["status"] == "Approved"  # the owner's own decision, as before
    assert lead_row(owned["id"]).owner_id == team["tara"]


def test_two_requests_for_one_lead_never_overwrite_the_first_approval(client, team):
    lead = pooled(client, 1, "Same")[0]
    ravi, tara = ask(client, RAVI, [lead])[0], ask(client, team["tara"], [lead])[0]
    body = decide(client, ASHA, "approve", [tara, ravi]).json()  # decided in id order: Ravi asked first
    assert [d["id"] for d in body["done"]] == [ravi]
    assert [c["id"] for c in body["conflicts"]] == [tara]
    assert body["conflicts"][0]["reason"].startswith("This request was already rejected by Asha Rao: The lead was assigned to Ravi Kumar")
    assert lead_row(lead).owner_id == RAVI  # Tara's request didn't take it
    # Tara heard once that her request was closed (by the assignment), not again for the bulk action
    assert [t for t, _ in bell(team["tara"])].count("Lead request closed") == 1


def test_sending_the_same_selection_again_decides_nothing_twice(client, team, outbox):
    leads = pooled(client, 2, "Twice")
    ids = ask(client, RAVI, leads)
    assert decide(client, ASHA, "approve", ids).json()["approved"] == 2
    before, ravi_bell, mails = counts(), len(bell(RAVI)), len(outbox)
    again = decide(client, ASHA, "approve", ids).json()  # a second click or a stale page
    assert (again["approved"], [c["id"] for c in again["conflicts"]]) == (0, ids)
    assert all(c["reason"].startswith("This request was already approved by Asha Rao") for c in again["conflicts"])
    rejected = decide(client, ASHA, "reject", ids, note="Synthetic: too late").json()
    assert (rejected["rejected"], len(rejected["conflicts"])) == (0, 2)  # an approval is never turned into a rejection
    assert counts() == before and len(bell(RAVI)) == ravi_bell and len(outbox) == mails  # no history, notice or email


def test_stale_requests_are_left_as_they_are_and_listed(client, team):
    leads = pooled(client, 3, "Stale")
    assigned, cancelled, kept = ask(client, RAVI, leads)
    # meanwhile: the Admin assigns one lead directly (its request is closed), and Ravi cancels another request
    assert login_as(client, ASHA).post(f"/api/leads/{leads[0]}/assign", json={"to_user_id": team["tara"]}).status_code == 200
    assert login_as(client, RAVI).post(f"/api/transfer-requests/{cancelled}/cancel").status_code == 200
    body = decide(client, ASHA, "approve", [assigned, cancelled, kept, 999999]).json()
    assert [d["id"] for d in body["done"]] == [kept]
    assert {c["id"]: c["reason"].split(":")[0] for c in body["conflicts"]} == {
        assigned: "This request was already rejected by Asha Rao", cancelled: "This request was already cancelled by Ravi Kumar"}
    assert [(s["id"], s["reason"]) for s in body["skipped"]] == [(999999, "Transfer request 999999 not found")]
    assert lead_row(leads[0]).owner_id == team["tara"]  # the direct assignment stands


def test_an_owned_leads_request_isnt_approved_once_the_lead_changed_hands(client, team):
    """A request for someone's lead names its owner then. If the lead was transferred since, approving it would take the
    lead from its new owner: it is refused (one request or several) and nothing moves."""
    owned = login_as(client, RAVI).post("/api/leads", json={"first_name": "Moved", "last_name": "Lead",
                                                             "company": "Moved Synthetic Co", "source": "Website",
                                                             "email": "moved@moved-synthetic.example"}).json()
    request_id = login_as(client, team["tara"]).post(f"/api/leads/{owned['id']}/transfer-requests",
                                                      json={"reason": REASON}).json()["id"]
    assert login_as(client, ASHA).post(f"/api/leads/{owned['id']}/transfer", json={"to_user_id": PRIYA}).status_code == 200
    body = decide(client, ASHA, "approve", [request_id]).json()
    assert body["approved"] == 0 and body["conflicts"][0]["reason"].startswith("The lead's owner changed since this request")
    single = login_as(client, ASHA).post(f"/api/transfer-requests/{request_id}/approve", json={})
    assert single.status_code == 409  # the same rule for one request
    assert lead_row(owned["id"]).owner_id == PRIYA and request_row(request_id).status == "Pending"
    # it can still be rejected (the requester is told why)
    assert decide(client, ASHA, "reject", [request_id], note="Synthetic: the lead moved").json()["rejected"] == 1


def test_reject_selected_needs_one_reason_and_tells_each_requester_once(client, team, outbox):
    leads = pooled(client, 3, "Reject")
    ravis, tara = ask(client, RAVI, leads[:2]), ask(client, team["tara"], [leads[2]])
    before = counts()
    for note in (None, "", "   "):
        res = decide(client, ASHA, "reject", [*ravis, *tara], note=note)
        assert res.status_code == 422 and res.json()["detail"] == "Say why the request is rejected"
    assert counts() == before  # nothing decided without a reason
    ravi_bell, tara_bell = len(bell(RAVI)), len(bell(team["tara"]))
    outbox.clear()
    body = decide(client, ASHA, "reject", [*ravis, *tara], note="Synthetic: outside your territory").json()
    assert body["rejected"] == 3
    assert [lead_row(i).owner_id for i in leads] == [None, None, None]  # the leads stay in the pool
    assert [(t, m.splitlines()[-1]) for t, m in bell(RAVI)[ravi_bell:]] == [
        ("Lead request rejected", "Reason: Synthetic: outside your territory")] * 2
    assert len(bell(team["tara"])) == tara_bell + 1
    assert sorted(m["to"][0] for m in outbox) == ["ravi@crm.test", "ravi@crm.test", "tara@crm.test"]


def test_notification_emails_follow_each_persons_settings(client, team, outbox):
    leads = pooled(client, 2, "Prefs")
    ravi, tara = ask(client, RAVI, [leads[0]])[0], ask(client, team["tara"], [leads[1]])[0]
    with db() as s:
        s.get(User, team["tara"]).email_assignments = False
        s.commit()
    outbox.clear()
    assert decide(client, ASHA, "approve", [ravi, tara]).json()["approved"] == 2
    assert [m["to"][0] for m in outbox] == ["ravi@crm.test"]  # Tara turned assignment emails off
    assert bell(team["tara"])[-1][0] == "Lead assigned to you"  # the bell still tells her


@pytest.mark.parametrize("ids", [[], list(range(1, 102))])
def test_a_bulk_decision_takes_one_to_100_requests(client, ids):
    res = decide(client, ASHA, "approve", ids)
    assert res.status_code == 422


# ---------- Requested By ----------

def page(client, user_id, **params):
    res = login_as(client, user_id).get("/api/transfer-requests/page", params={"box": "to_approve", **params})
    assert res.status_code == 200, res.text
    return res.json()


def test_requested_by_filters_the_whole_box_before_paging(client, team):
    leads = pooled(client, 7, "Filter")
    ravis, taras = ask(client, RAVI, leads[:5]), ask(client, team["tara"], leads[5:])
    everyone = page(client, ASHA, limit=2)
    assert (everyone["total"], len(everyone["items"])) == (7, 2)
    assert everyone["requesters"] == [{"id": RAVI, "name": "Ravi Kumar", "count": 5},
                                      {"id": team["tara"], "name": "Tara Nair", "count": 2}]
    seen = []
    for offset in (0, 2, 4):
        one = page(client, ASHA, requested_by_id=RAVI, limit=2, offset=offset)
        assert one["total"] == 5 and one["box_total"] == 7  # counted on the server, not from the loaded page
        assert {r["requested_by_id"] for r in one["items"]} == {RAVI}
        seen += [r["id"] for r in one["items"]]
    assert sorted(seen) == sorted(ravis)  # every page once, nothing missing or repeated
    assert page(client, ASHA, requested_by_id=team["tara"])["total"] == len(taras)


def test_requested_by_offers_only_people_the_approver_may_see(client, team):
    leads = pooled(client, 3, "Who")
    ask(client, RAVI, [leads[0]])
    ask(client, team["tara"], [leads[1]])
    ask(client, team["sam"], [leads[2]])
    priya, mona = page(client, PRIYA), page(client, team["mona"])
    assert [p["name"] for p in priya["requesters"]] == ["Ravi Kumar", "Tara Nair"]  # her team only
    assert [p["name"] for p in mona["requesters"]] == ["Sam Roy"]
    # asking for someone outside the team shows nothing (not even that they have requests)
    other = page(client, team["mona"], requested_by_id=RAVI)
    assert (other["total"], other["items"]) == (0, [])
    assert page(client, RAVI)["requesters"] == []  # a Salesperson approves nothing from the pool


def test_the_filter_works_with_bulk_decisions_and_the_counts_follow(client, team):
    leads = pooled(client, 4, "Mixed")
    ravis, tara = ask(client, RAVI, leads[:3]), ask(client, team["tara"], [leads[3]])
    shown = page(client, ASHA, requested_by_id=RAVI, limit=2)
    ticked = [r["id"] for r in shown["items"]]  # "select all on this page": these two only
    assert decide(client, ASHA, "approve", ticked).json()["approved"] == 2
    after = page(client, ASHA, requested_by_id=RAVI, limit=2)
    assert after["total"] == 1 and [r["id"] for r in after["items"]] == sorted(set(ravis) - set(ticked))
    assert {p["name"]: p["count"] for p in after["requesters"]} == {"Ravi Kumar": 1, "Tara Nair": 1}
    assert request_row(tara[0]).status == "Pending"  # hidden by the filter: never decided


def test_a_notification_link_opens_the_page_that_holds_its_request(client, team):
    leads = pooled(client, 5, "Focus")
    ids = ask(client, RAVI, leads)
    oldest = min(ids)  # newest first: the oldest is on the last page
    shown = page(client, ASHA, box="all", limit=2, focus=oldest)
    assert shown["offset"] == 4 and [r["id"] for r in shown["items"]] == [oldest]
    # the old list (500 rows) still answers as before
    assert {r["id"] for r in login_as(client, ASHA).get("/api/transfer-requests", params={"box": "to_approve"}).json()} == set(ids)
