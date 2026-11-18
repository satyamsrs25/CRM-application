"""The Unassigned Pool: every bulk upload starts with no owner. Only the Admin and Managers with Reassign owner (to
their own Salespeople) assign a pooled lead, one at a time; Salespeople can only request one. Campaign access follows
ownership. Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin), plus the people added below.
All data is made up."""
import csv
import io
from datetime import timedelta

import pytest

from app import campaigns, mailer
from app.database import get_db
from app.main import app
from app.models import Campaign, Lead, LeadTransfer, LeadTransferRequest, Notification, RolePermission, User
from app.services import now
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3
REASON = "I spoke to this synthetic customer at the expo"
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject}))
    return sent


@pytest.fixture
def sent(monkeypatch):
    """Campaign emails "sent" (send_one is replaced: nothing leaves the test)."""
    monkeypatch.setenv("CAMPAIGN_CHECK_DOMAINS", "false")
    monkeypatch.setenv("CAMPAIGN_PER_DAY", "1800")
    items = []
    monkeypatch.setattr(campaigns, "send_one", lambda to, subject, body, **kw: items.append(to) or campaigns.Result("sent"))
    return items


def db():
    return next(app.dependency_overrides[get_db]())


def add_user(full_name, email, role, **fields) -> int:
    with db() as s:
        user = User(full_name=full_name, email=email, role=role, password_hash="x", **fields)
        s.add(user)
        s.commit()
        return user.id


@pytest.fixture
def team(client):
    """Two teams: Priya (Ravi, Tara) and Mona (Sam). Leo is a Salesperson with no Manager."""
    with db() as s:
        s.get(User, RAVI).reports_to_id = PRIYA
        s.commit()
    mona = add_user("Mona Iyer", "mona@crm.test", "Manager")
    return {"tara": add_user("Tara Nair", "tara@crm.test", "Salesperson", reports_to_id=PRIYA),
            "mona": mona,
            "sam": add_user("Sam Roy", "sam@crm.test", "Salesperson", reports_to_id=mona),
            "leo": add_user("Leo Das", "leo@crm.test", "Salesperson")}


def upload(client, rows, **form):
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Last Name", "Company", "Email", "Phone", "Lead Owner"], *rows])
    res = client.post("/api/leads/import", files={"file": ("pool.csv", out.getvalue().encode(), "text/csv")},
                      data={"dry_run": "false", **form})
    assert res.status_code == 200, res.text
    return res.json()


def pool_rows(n, prefix="Pool", owner=""):
    return [["Ana", f"{prefix}{chr(65 + i % 26)}{chr(65 + i // 26 % 26)}", "Pool Synthetic Co",
             f"{prefix.lower()}{i}@pool-synthetic.example", "", owner] for i in range(n)]  # phones are optional


def pooled_ids(client, as_user=ASHA):
    items = login_as(client, as_user).get("/api/leads/page", params={"view": "unassigned", "limit": 500}).json()["items"]
    return [l["id"] for l in items]


def lead_row(lead_id) -> Lead:
    with db() as s:
        lead = s.get(Lead, lead_id)
        s.expunge(lead)
        return lead


def bell(user_id):
    with db() as s:
        return [(n.title, n.message) for n in s.query(Notification).filter_by(user_id=user_id).order_by(Notification.id)]


def without(role, permission):
    with db() as s:
        s.add(RolePermission(role=role, permission=permission, allowed=False))
        s.commit()


def own_lead(client, user_id, last="Owned", email="owned@pool-synthetic.example"):
    res = login_as(client, user_id).post("/api/leads", json={"first_name": "Omar", "last_name": last,
                                                              "company": "Owned Synthetic Co", "source": "Website",
                                                              "email": email})
    assert res.status_code == 201, res.text
    return res.json()


# ---------- uploads ----------

def test_every_role_uploads_into_the_pool_and_existing_owners_stay(client, team, outbox):
    mine = own_lead(client, RAVI)
    for user, prefix in ((RAVI, "Seller"), (PRIYA, "Manager"), (ASHA, "Admin")):
        done = upload(login_as(client, user), pool_rows(2, prefix, owner="ravi@crm.test"), owner_id=str(RAVI))
        assert done["created"] == 2 and done["owner"] == "Unassigned Pool"
    items = login_as(client, ASHA).get("/api/leads/page", params={"view": "unassigned"}).json()["items"]
    assert len(items) == 6 and {l["owner_id"] for l in items} == {None}
    assert sorted(l["created_by_id"] for l in items) == [PRIYA, PRIYA, RAVI, RAVI, ASHA, ASHA]
    assert all(l["stage"] == "New" and l["in_pool"] and l["assigned_at"] is None for l in items)
    assert lead_row(mine["id"]).owner_id == RAVI  # an existing lead keeps its owner
    assert all(t not in ("Leads assigned to you", "Leads created for your team") for u in (PRIYA, RAVI) for t, _ in bell(u))
    # duplicate detection still sees pooled leads
    again = login_as(client, RAVI).post("/api/leads/import", data={"dry_run": "true"}, files={
        "file": ("again.csv", b"Last Name,Company,Email\nAgain,Pool Synthetic Co,seller0@pool-synthetic.example\n", "text/csv")})
    assert again.json()["duplicates"] == 1


# ---------- what pooled visibility does and doesn't allow ----------

def test_a_salesperson_sees_the_pool_without_contacts_and_cannot_act_on_it(client, team):
    upload(login_as(client, ASHA), pool_rows(3))
    lead_id = pooled_ids(client)[0]
    ravi = login_as(client, RAVI)
    page = ravi.get("/api/leads/page", params={"view": "unassigned"}).json()
    assert page["total"] == 3
    assert all(l["contact_hidden"] and l["email"] is None and l["phone"] is None for l in page["items"])
    assert all(l["company"] == "Pool Synthetic Co" for l in page["items"])  # enough to decide whether to ask
    # contact details can't be found by searching or sorting on them either
    assert ravi.get("/api/leads/page", params={"view": "unassigned", "search": "pool0@"}).json()["total"] == 0
    assert ravi.get("/api/leads/page", params={"view": "unassigned", "sort": "email"}).status_code == 200
    # the pool isn't in his own lists
    assert ravi.get("/api/leads/page", params={"view": "all_open"}).json()["total"] == 0
    detail = ravi.get(f"/api/leads/{lead_id}").json()
    assert detail["contact_hidden"] and detail["email"] is None and detail["linkedin_url"] is None
    assert detail["notes"] == [] and detail["owner_id"] is None
    # nothing else: no edit, stage change, conversion, closing, delete, transfer, assignment, task or email status
    attempts = [
        ravi.put(f"/api/leads/{lead_id}", json={"title": "Changed"}),
        ravi.put(f"/api/leads/{lead_id}", json={"owner_id": RAVI}),
        ravi.put(f"/api/leads/{lead_id}/stage", json={"stage": "Nurturing", "note": "Synthetic", "task": TASK,
                                                      "completed_stages": ["New"]}),
        ravi.post(f"/api/leads/{lead_id}/convert", json={"note": "Synthetic", "task": TASK,
                                                         "completed_stages": ["New", "Nurturing", "Demo"]}),
        ravi.post(f"/api/leads/{lead_id}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic"}),
        ravi.delete(f"/api/leads/{lead_id}"),
        ravi.post(f"/api/leads/{lead_id}/transfer", json={"to_user_id": RAVI}),
        ravi.post("/api/leads/bulk-transfer", json={"lead_ids": [lead_id], "to_user_id": RAVI}),
        ravi.post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI}),
        ravi.post("/api/tasks", json={**TASK, "lead_id": lead_id}),
        ravi.post(f"/api/leads/{lead_id}/email-status", json={"status": "invalid", "reason": "Synthetic"}),
    ]
    for res in attempts:
        assert res.status_code in (400, 403, 404, 422) or res.json().get("transferred") == 0, res.text
    assert lead_row(lead_id).owner_id is None and lead_row(lead_id).stage == "New"
    # downloads: only his own leads, so no pooled lead
    file = ravi.get("/api/leads/export", params={"reason": "Synthetic check", "format": "csv"})
    assert file.status_code == 200 and "Pool Synthetic Co" not in file.content.decode("utf-8-sig")


def test_a_manager_sees_the_pool_but_stage_changes_and_transfers_wait_for_assignment(client, team):
    upload(login_as(client, ASHA), pool_rows(2))
    lead_id = pooled_ids(client)[0]
    priya = login_as(client, PRIYA)
    detail = priya.get(f"/api/leads/{lead_id}").json()
    assert not detail["contact_hidden"] and detail["email"].endswith("@pool-synthetic.example")
    stage = priya.put(f"/api/leads/{lead_id}/stage", json={"stage": "Nurturing", "note": "Synthetic", "task": TASK,
                                                           "completed_stages": ["New"]})
    assert stage.status_code == 400 and "Unassigned Pool" in stage.json()["detail"]
    for res in (priya.post(f"/api/leads/{lead_id}/transfer", json={"to_user_id": RAVI}),
                priya.put(f"/api/leads/{lead_id}", json={"owner_id": RAVI}),
                priya.post(f"/api/leads/{lead_id}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic"}),
                priya.post("/api/tasks", json={**TASK, "lead_id": lead_id})):
        assert res.status_code == 400 and "Unassigned Pool" in res.json()["detail"], res.text
    bulk = priya.post("/api/leads/bulk-transfer", json={"lead_ids": [lead_id], "to_user_id": RAVI}).json()
    assert bulk["transferred"] == 0 and "Unassigned Pool" in bulk["skipped"][0]["reason"]
    # a field fix is still an edit (Edit team records), and leaves it in the pool
    assert priya.put(f"/api/leads/{lead_id}", json={"title": "Synthetic CTO"}).status_code == 200
    assert lead_row(lead_id).owner_id is None


# ---------- assignment ----------

def test_assigning_one_lead_changes_only_the_owner_and_records_it(client, team, outbox):
    upload(login_as(client, RAVI), pool_rows(1))  # Ravi uploads: he is Created By, not the owner
    lead_id = pooled_ids(client)[0]
    before = lead_row(lead_id)
    res = login_as(client, PRIYA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": team["tara"],
                                                                             "note": "Synthetic territory"})
    assert res.status_code == 200, res.text
    lead = res.json()
    assert (lead["owner_id"], lead["stage"], lead["created_by_id"]) == (team["tara"], "New", RAVI)
    assert lead["created_at"] == before.created_at.isoformat() and lead["assigned_at"] and lead["owner_since"]
    assert lead["in_pool"] is False and lead["untouched"] is True
    [move] = lead["transfers"]
    assert (move["from_user_id"], move["to_user_id"], move["transferred_by_id"], move["note"], move["request_id"]) == \
        (None, team["tara"], PRIYA, "Synthetic territory", None)
    assert [t for t, _ in bell(team["tara"])] == ["Lead assigned to you"]
    assert bell(RAVI) == []  # the uploader has nothing to do with it
    assert [m["to"] for m in outbox] == [["tara@crm.test"]]
    # assigning again: a conflict, the owner stays
    again = login_as(client, ASHA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI})
    assert again.status_code == 409 and "Tara Nair" in again.json()["detail"]
    assert lead_row(lead_id).owner_id == team["tara"]
    # an assigned lead is worked on as usual, and is not claimable from the pool any more
    tara = login_as(client, team["tara"])
    assert tara.put(f"/api/leads/{lead_id}/stage", json={"stage": "Nurturing", "note": "Synthetic", "task": TASK,
                                                         "completed_stages": ["New"]}).status_code == 200
    assert lead_id not in pooled_ids(client)


def test_who_can_assign_and_to_whom(client, team):
    upload(login_as(client, ASHA), pool_rows(4))
    a, b, c, d = pooled_ids(client)
    priya = login_as(client, PRIYA)
    assert priya.post(f"/api/leads/{a}/assign", json={"to_user_id": team["sam"]}).status_code == 403  # Mona's team
    assert priya.post(f"/api/leads/{a}/assign", json={"to_user_id": team["leo"]}).status_code == 403  # no Manager
    for target in (PRIYA, ASHA, team["mona"], 999):  # Managers and the Admin don't take pooled leads; unknown user
        assert priya.post(f"/api/leads/{a}/assign", json={"to_user_id": target}).status_code == 400
    with db() as s:
        s.get(User, team["tara"]).is_active = False
        s.commit()
    assert priya.post(f"/api/leads/{a}/assign", json={"to_user_id": team["tara"]}).status_code == 400  # deactivated
    assert lead_row(a).owner_id is None
    # Mona assigns to her own team; the Admin to anyone
    assert login_as(client, team["mona"]).post(f"/api/leads/{a}/assign", json={"to_user_id": team["sam"]}).status_code == 200
    assert login_as(client, ASHA).post(f"/api/leads/{b}/assign", json={"to_user_id": team["leo"]}).status_code == 200
    # Salespeople never assign or claim, even with "Transfer own leads" or team access
    with db() as s:
        s.get(User, RAVI).team_access = True
        s.commit()
    ravi = login_as(client, RAVI)
    assert ravi.post(f"/api/leads/{c}/assign", json={"to_user_id": RAVI}).status_code == 403
    assert ravi.post(f"/api/leads/{c}/transfer", json={"to_user_id": RAVI}).status_code in (400, 403)
    # a Manager whose role lost "Reassign owner" can't assign either
    without("Manager", "reassign_owner")
    assert login_as(client, PRIYA).post(f"/api/leads/{d}/assign", json={"to_user_id": RAVI}).status_code == 403
    assert lead_row(c).owner_id is None and lead_row(d).owner_id is None


# ---------- requests for pooled leads ----------

def test_request_approval_by_the_requesters_manager_assigns_the_lead(client, team, outbox):
    upload(login_as(client, team["tara"]), pool_rows(1))  # Tara uploaded it: no say in who gets it
    lead_id = pooled_ids(client)[0]
    ravi = login_as(client, RAVI)
    assert ravi.post(f"/api/leads/{lead_id}/transfer-requests", json={"reason": ""}).status_code == 422
    asked = ravi.post(f"/api/leads/{lead_id}/transfer-requests", json={"reason": REASON})
    assert asked.status_code == 201, asked.text
    request = asked.json()
    assert request["pool"] and request["owner_id"] is None and request["can_open_lead"]
    assert ravi.post(f"/api/leads/{lead_id}/transfer-requests", json={"reason": REASON}).status_code == 409  # twice
    # asking gives nothing: still pooled, no contact details, no edits
    assert lead_row(lead_id).owner_id is None
    assert ravi.get(f"/api/leads/{lead_id}").json()["contact_hidden"]
    assert ravi.put(f"/api/leads/{lead_id}", json={"title": "Mine now?"}).status_code in (403, 404)
    # who is told: the Admin and Ravi's Manager (not Tara, not Mona)
    assert [t for t, _ in bell(PRIYA)] == ["Lead requested from the Unassigned Pool"]
    assert [t for t, _ in bell(ASHA)] == ["Lead requested from the Unassigned Pool"]
    assert bell(team["tara"]) == [] and bell(team["mona"]) == []
    # who can decide: not the requester, the uploader or another team's Manager
    for user in (RAVI, team["tara"], team["mona"]):
        assert login_as(client, user).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 403
    assert [r["id"] for r in login_as(client, PRIYA).get("/api/transfer-requests", params={"box": "to_approve"}).json()] \
        == [request["id"]]
    assert login_as(client, team["mona"]).get("/api/transfer-requests", params={"box": "to_approve"}).json() == []
    done = login_as(client, PRIYA).post(f"/api/transfer-requests/{request['id']}/approve", json={"note": "Synthetic ok"})
    assert done.status_code == 200 and done.json()["status"] == "Approved"
    lead = lead_row(lead_id)
    assert (lead.owner_id, lead.stage, lead.created_by_id) == (RAVI, "New", team["tara"])
    with db() as s:
        [move] = s.query(LeadTransfer).filter_by(lead_id=lead_id).all()
        assert (move.from_user_id, move.to_user_id, move.transferred_by_id, move.request_id) == \
            (None, RAVI, PRIYA, request["id"])
    assert [t for t, _ in bell(RAVI)] == ["Lead assigned to you"]  # one notice, not two
    assert sum(1 for m in outbox if m["to"] == ["ravi@crm.test"]) == 1
    # approving again is a conflict
    assert login_as(client, ASHA).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 409


def test_competing_requests_reject_cancel_and_stale_approvals(client, team):
    upload(login_as(client, ASHA), pool_rows(2))
    first, second = pooled_ids(client)
    ravi_req = login_as(client, RAVI).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).json()
    tara_req = login_as(client, team["tara"]).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).json()
    sam_req = login_as(client, team["sam"]).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).json()
    # Managers and the Admin don't request: they assign
    assert login_as(client, PRIYA).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).status_code == 400
    assert login_as(client, ASHA).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).status_code == 400
    # Mona approves Sam's: the lead is Sam's, every other request is closed and can't be approved any more
    assert login_as(client, team["mona"]).post(f"/api/transfer-requests/{sam_req['id']}/approve", json={}).status_code == 200
    with db() as s:
        statuses = {r.id: (r.status, r.decision_note) for r in s.query(LeadTransferRequest).all()}
    assert statuses[ravi_req["id"]] == ("Rejected", "The lead was assigned to Sam Roy")
    assert statuses[tara_req["id"]][0] == "Rejected"
    late = login_as(client, PRIYA).post(f"/api/transfer-requests/{ravi_req['id']}/approve", json={})
    assert late.status_code == 409 and "assigned to Sam Roy" in late.json()["detail"]
    assert lead_row(first).owner_id == team["sam"]
    assert ("Lead request closed" in [t for t, _ in bell(RAVI)]) and ("Lead request closed" in [t for t, _ in bell(team["tara"])])
    # rejecting needs a reason; cancelling is the requester's
    req = login_as(client, RAVI).post(f"/api/leads/{second}/transfer-requests", json={"reason": REASON}).json()
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{req['id']}/reject", json={}).status_code == 422
    assert login_as(client, team["mona"]).post(f"/api/transfer-requests/{req['id']}/reject",
                                               json={"note": "Synthetic"}).status_code == 403
    assert login_as(client, team["tara"]).post(f"/api/transfer-requests/{req['id']}/cancel").status_code == 403
    assert login_as(client, RAVI).post(f"/api/transfer-requests/{req['id']}/cancel").json()["status"] == "Cancelled"
    again = login_as(client, RAVI).post(f"/api/leads/{second}/transfer-requests", json={"reason": REASON}).json()
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{again['id']}/reject",
                                        json={"note": "Synthetic: not now"}).json()["status"] == "Rejected"
    assert lead_row(second).owner_id is None
    # a direct assignment closes pending requests too
    third = login_as(client, team["tara"]).post(f"/api/leads/{second}/transfer-requests", json={"reason": REASON}).json()
    assert login_as(client, ASHA).post(f"/api/leads/{second}/assign", json={"to_user_id": team["leo"]}).status_code == 200
    stale = login_as(client, PRIYA).post(f"/api/transfer-requests/{third['id']}/approve", json={})
    assert stale.status_code == 409 and lead_row(second).owner_id == team["leo"]


def test_without_an_authorised_manager_only_the_admin_approves(client, team):
    upload(login_as(client, ASHA), pool_rows(2))
    first, second = pooled_ids(client)
    leo_req = login_as(client, team["leo"]).post(f"/api/leads/{first}/transfer-requests", json={"reason": REASON}).json()
    assert [t for t, _ in bell(ASHA)] == ["Lead requested from the Unassigned Pool"]  # Leo has no Manager
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{leo_req['id']}/approve", json={}).status_code == 403
    without("Manager", "reassign_owner")
    ravi_req = login_as(client, RAVI).post(f"/api/leads/{second}/transfer-requests", json={"reason": REASON}).json()
    assert bell(PRIYA) == []  # Priya can't assign pooled leads now, so she isn't asked
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{ravi_req['id']}/approve", json={}).status_code == 403
    assert login_as(client, ASHA).post(f"/api/transfer-requests/{ravi_req['id']}/approve", json={}).status_code == 200
    assert lead_row(second).owner_id == RAVI


def test_requests_for_owned_leads_work_as_before_and_record_the_request(client, team):
    priyas = own_lead(client, PRIYA)
    req = login_as(client, RAVI).post(f"/api/leads/{priyas['id']}/transfer-requests", json={"reason": REASON}).json()
    assert req["pool"] is False and req["owner_id"] == PRIYA
    assert login_as(client, team["mona"]).post(f"/api/transfer-requests/{req['id']}/approve", json={}).status_code == 403
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{req['id']}/approve", json={}).status_code == 200
    lead = login_as(client, RAVI).get(f"/api/leads/{priyas['id']}").json()
    assert lead["owner_id"] == RAVI and lead["transfers"][0]["request_id"] == req["id"]
    assert lead["transfers"][0]["from_user_id"] == PRIYA and lead["assigned_at"]
    # the owner (with Transfer own leads) still transfers directly; an owned lead never goes back to the pool
    assert login_as(client, RAVI).post(f"/api/leads/{priyas['id']}/transfer",
                                       json={"to_user_id": team["tara"]}).status_code == 200
    assert priyas["id"] not in pooled_ids(client)


# ---------- several pooled leads requested at once ----------

def links(user_id):
    with db() as s:
        return [(n.title, n.link) for n in s.query(Notification).filter_by(user_id=user_id).order_by(Notification.id)]


def test_a_salesperson_requests_several_pooled_leads_with_one_reason(client, team, outbox):
    upload(login_as(client, ASHA), pool_rows(6))
    a, b, c, d, e, f = pooled_ids(client)
    ravi = login_as(client, RAVI)
    single = ravi.post(f"/api/leads/{a}/transfer-requests", json={"reason": REASON}).json()  # asked for already
    assert login_as(client, ASHA).post(f"/api/leads/{e}/assign", json={"to_user_id": team["tara"]}).status_code == 200
    before = {u: len(bell(u)) for u in (PRIYA, ASHA, team["mona"])}
    res = login_as(client, RAVI).post("/api/transfer-requests/bulk", json={"lead_ids": [a, b, c, d, e, 999999, b],
                                                                          "reason": "Synthetic: my territory"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requested"] == 3 and sorted(r["lead_id"] for r in body["created"]) == sorted([b, c, d])
    assert [(r["lead_id"], r["reason"]) for r in body["conflicts"]] == \
        [(e, "No longer in the Unassigned Pool: assigned since you selected it")]
    assert {(r["lead_id"], r["reason"]) for r in body["skipped"]} == \
        {(a, "You have already asked for this lead"), (999999, "Not found")}
    assert set(body["sent_to"]) == {"Asha Rao", "Priya Sharma"}
    assert "your Manager, Priya Sharma, and the Admin" in body["routing"]
    # requests only: nothing is assigned, each lead has its own pending request
    assert [lead_row(x).owner_id for x in (b, c, d, f)] == [None, None, None, None]
    with db() as s:
        pending = s.query(LeadTransferRequest).filter_by(requested_by_id=RAVI, status="Pending").all()
        assert sorted(r.lead_id for r in pending) == sorted([a, b, c, d])
        assert {r.reason for r in pending if r.lead_id != a} == {"Synthetic: my territory"}
    # one summary each for the Admin and Ravi's Manager, nobody else, linking to To Approve
    for user in (PRIYA, ASHA):
        [(title, link)] = links(user)[before[user]:]
        assert (title, link) == ("Leads requested from the Unassigned Pool", "/transfer-requests?box=to_approve")
        assert "asked for 3 leads" in bell(user)[-1][1]
    assert len(bell(team["mona"])) == before[team["mona"]]
    # the single request linked to that request
    assert ("Lead requested from the Unassigned Pool", f"/transfer-requests?request={single['id']}") in links(PRIYA)
    # what the approvers see agrees with who was told and who may decide
    for user in (PRIYA, ASHA):
        box = login_as(client, user).get("/api/transfer-requests", params={"box": "to_approve"}).json()
        assert sorted(r["lead_id"] for r in box if r["requested_by_id"] == RAVI) == sorted([a, b, c, d])
        assert all(r["can_decide"] for r in box)
    assert login_as(client, team["mona"]).get("/api/transfer-requests", params={"box": "to_approve"}).json() == []
    # each request is decided on its own; the requester hears each outcome once
    ids = {r["lead_id"]: r["id"] for r in body["created"]}
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{ids[b]}/approve", json={}).status_code == 200
    assert login_as(client, ASHA).post(f"/api/transfer-requests/{ids[c]}/reject",
                                       json={"note": "Synthetic: not now"}).status_code == 200
    # the other approver's decision comes too late and changes nothing
    late = login_as(client, ASHA).post(f"/api/transfer-requests/{ids[b]}/reject", json={"note": "Synthetic"})
    assert late.status_code == 409 and "approved" in late.json()["detail"]
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{ids[c]}/approve", json={}).status_code == 409
    assert (lead_row(b).owner_id, lead_row(c).owner_id, lead_row(d).owner_id) == (RAVI, None, None)
    titles = [t for t, _ in bell(RAVI)]
    assert titles.count("Lead assigned to you") == 1 and titles.count("Lead request rejected") == 1
    assert ("Lead request rejected", f"/transfer-requests?request={ids[c]}") in links(RAVI)


def test_bulk_requests_follow_the_same_rules_and_limits(client, team):
    upload(login_as(client, ASHA), pool_rows(3))
    a, b, c = pooled_ids(client)
    for user in (PRIYA, ASHA):  # Managers and the Admin assign instead
        assert login_as(client, user).post("/api/transfer-requests/bulk",
                                           json={"lead_ids": [a], "reason": REASON}).status_code == 400
    ravi = login_as(client, RAVI)
    assert ravi.post("/api/transfer-requests/bulk", json={"lead_ids": [a], "reason": "  "}).status_code == 422
    assert ravi.post("/api/transfer-requests/bulk", json={"lead_ids": [], "reason": REASON}).status_code == 422
    assert ravi.post("/api/transfer-requests/bulk", json={"lead_ids": list(range(1, 502)), "reason": REASON}).status_code == 422
    # only the ticked leads are requested, never the rest of the pool
    assert ravi.post("/api/transfer-requests/bulk", json={"lead_ids": [a, b], "reason": REASON}).json()["requested"] == 2
    with db() as s:
        assert s.query(LeadTransferRequest).filter_by(lead_id=c).count() == 0
    # the same leads again: nothing new, each one says why
    again = ravi.post("/api/transfer-requests/bulk", json={"lead_ids": [a, b], "reason": REASON}).json()
    assert again["requested"] == 0 and len(again["skipped"]) == 2


def test_without_an_eligible_manager_only_the_admin_is_asked_and_told_why(client, team):
    upload(login_as(client, ASHA), pool_rows(2))
    first, second = pooled_ids(client)
    # Leo has no Manager in Reports To
    leo = login_as(client, team["leo"]).post("/api/transfer-requests/bulk",
                                              json={"lead_ids": [first], "reason": REASON}).json()
    assert leo["sent_to"] == ["Asha Rao"] and "no Manager in Reports To" in leo["routing"]
    assert [t for t, _ in bell(ASHA)] == ["Lead requested from the Unassigned Pool"]
    assert bell(PRIYA) == [] and bell(team["mona"]) == []
    # Ravi's Manager can't assign pooled leads now: Admin only, and the list agrees
    without("Manager", "reassign_owner")
    ravi = login_as(client, RAVI).post(f"/api/leads/{second}/transfer-requests", json={"reason": REASON}).json()
    assert ravi["sent_to"] == ["Asha Rao"] and "Reassign owner" in ravi["routing"]
    assert bell(PRIYA) == []
    assert login_as(client, PRIYA).get("/api/transfer-requests", params={"box": "to_approve"}).json() == []
    assert {r["lead_id"] for r in login_as(client, ASHA).get("/api/transfer-requests",
                                                             params={"box": "to_approve"}).json()} == {first, second}


def test_direct_assignment_needs_no_request(client, team, outbox):
    upload(login_as(client, ASHA), pool_rows(2))
    first, second = pooled_ids(client)
    with db() as s:
        assert s.query(LeadTransferRequest).count() == 0
    assert login_as(client, PRIYA).post(f"/api/leads/{first}/assign", json={"to_user_id": RAVI}).status_code == 200
    assert login_as(client, ASHA).post(f"/api/leads/{second}/assign", json={"to_user_id": team["leo"]}).status_code == 200
    assert (lead_row(first).owner_id, lead_row(second).owner_id) == (RAVI, team["leo"])


# ---------- campaigns ----------

def make_campaign(client, lead_ids=(), emails=()):
    return client.post("/api/campaigns", json={"name": "Pool check", "subject": "Hello {first_name}",
                                               "body": "Hello {first_name}, a synthetic note.",
                                               "lead_ids": list(lead_ids), "emails": [{"email": e} for e in emails]})


def run_round():
    s = db()
    try:
        return campaigns.run(s, pause_seconds=0)
    finally:
        s.close()


def test_campaigns_reach_pooled_leads_only_for_the_admin_and_authorised_managers(client, team, sent):
    upload(login_as(client, ASHA), pool_rows(2))
    pooled = pooled_ids(client)
    pooled_email = lead_row(pooled[0]).email
    ravis = own_lead(client, RAVI, "Seller", "seller.own@pool-synthetic.example")
    taras = own_lead(client, team["tara"], "Teammate", "tara.own@pool-synthetic.example")
    with db() as s:
        s.get(User, RAVI).team_access = True  # sees the team's records: still can't email them
        s.commit()
    ravi = login_as(client, RAVI)
    preview = ravi.post("/api/campaigns/preview", json={"lead_ids": [*pooled, ravis["id"], taras["id"]],
                                                        "emails": [{"email": pooled_email.upper()},
                                                                   {"email": "tara.own@pool-synthetic.example"},
                                                                   {"email": "stranger@outside-synthetic.example"}]}).json()
    assert preview["eligible"] == 2  # his own lead and the address that is nobody's lead
    assert preview["reasons"]["not_allowed"] == 5
    hidden = [r for r in preview["left_out_sample"] if r["reason"].startswith("Not yours")]
    assert len(hidden) == 5 and all(r["id"] is None for r in hidden)
    assert not any("Teammate" in (r["name"] or "") or "Ana" == (r["name"] or "") for r in hidden)  # no lead details
    made = make_campaign(ravi, [*pooled, ravis["id"], taras["id"]], [pooled_email]).json()
    assert made["counts"]["Queued"] == 1
    run_round()
    assert sent == ["seller.own@pool-synthetic.example"]
    # Priya (Manager: team records and Reassign owner) may email pooled and team leads; the Admin anything
    assert login_as(client, PRIYA).post("/api/campaigns/preview", json={
        "lead_ids": [*pooled, ravis["id"], taras["id"]]}).json()["eligible"] == 4
    assert login_as(client, ASHA).post("/api/campaigns/preview", json={"lead_ids": pooled}).json()["eligible"] == 2
    # a Manager without Reassign owner: team leads yes, pooled leads no
    without("Manager", "reassign_owner")
    preview = login_as(client, PRIYA).post("/api/campaigns/preview", json={"lead_ids": [*pooled, taras["id"]]}).json()
    assert (preview["eligible"], preview["reasons"]["not_allowed"]) == (1, 2)
    # the Send email campaigns permission still applies
    without("Salesperson", "send_campaigns")
    assert login_as(client, RAVI).post("/api/campaigns/preview", json={"lead_ids": [ravis["id"]]}).status_code == 403


def test_a_lead_given_away_before_its_turn_is_not_emailed(client, team, sent):
    first = own_lead(client, RAVI, "First", "first.turn@pool-synthetic.example")
    second = own_lead(client, RAVI, "Second", "second.turn@pool-synthetic.example")
    ravi = login_as(client, RAVI)
    made = ravi.post("/api/campaigns", json={"name": "Later", "subject": "Hello", "body": "Hello there, synthetic.",
                                             "lead_ids": [first["id"], second["id"]],
                                             "send_at": "2099-01-01T10:00:00"}).json()
    assert made["counts"]["Queued"] == 2
    # between preview and send, the first lead goes to Tara
    assert login_as(client, ASHA).post(f"/api/leads/{first['id']}/transfer", json={"to_user_id": team["tara"]}).status_code == 200
    with db() as s:  # its time comes
        s.get(Campaign, made["id"]).send_at = now() - timedelta(minutes=1)
        s.commit()
    result = run_round()
    assert (result["sent"], result["skipped"]) == (1, 1), result
    assert sent == ["second.turn@pool-synthetic.example"]
    rows = login_as(client, RAVI).get(f"/api/campaigns/{made['id']}", params={"status": "Skipped"}).json()
    assert rows["recipients"]["items"][0]["error"].startswith("Not yours")


# ---------- large pools: one page at a time, exact counts ----------

def test_the_pool_pages_with_exact_counts_and_counts_for_nobody(client, team):
    upload(login_as(client, ASHA), pool_rows(260, "Big"))
    ravis = own_lead(client, RAVI)
    priya = login_as(client, PRIYA)
    first = priya.get("/api/leads/page", params={"view": "unassigned", "limit": 100}).json()
    last = priya.get("/api/leads/page", params={"view": "unassigned", "limit": 100, "offset": 200}).json()
    assert (first["total"], len(first["items"]), len(last["items"])) == (260, 100, 60)
    assert not {l["id"] for l in first["items"]} & {l["id"] for l in last["items"]}
    # the board: Unassigned column (owner=unassigned) + stage columns of assigned leads = every lead, once
    pool = priya.get("/api/leads/page", params={"view": "all_open", "owner": "unassigned", "limit": 5}).json()["total"]
    new = priya.get("/api/leads/page", params={"view": "all_open", "stage": "New", "assigned": "true", "limit": 5}).json()
    everything = priya.get("/api/leads/page", params={"view": "all_open", "limit": 1}).json()["total"]
    assert (pool, new["total"], everything) == (260, 1, 261) and new["items"][0]["id"] == ravis["id"]
    # the Salesperson sees the same exact count, page by page
    ravi = login_as(client, RAVI)
    assert ravi.get("/api/leads/page", params={"owner": "unassigned", "limit": 50, "offset": 250}).json()["total"] == 260
    counts = login_as(client, ASHA).get("/api/leads/open-counts").json()["counts"]
    assert counts == {str(RAVI): 1}
