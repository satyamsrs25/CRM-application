"""Lead transfer requests: a user asks for someone else's lead, and the lead's owner, the owner's Manager or the Admin
must approve before it moves. Also the lead list's Created By and Transferred To columns. All data is made up."""
from sqlalchemy import select, update

from app.database import get_db
from app.main import app
from app.models import Lead, LeadTransfer, Notification
from conftest import login_as
from test_opportunity_duplicates import new_lead

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin
PASSWORD = "Synthetic@2026"


def database():
    return next(app.dependency_overrides[get_db]())


def titles(user_id: int) -> list[str]:
    return [n.title for n in database().scalars(select(Notification).where(Notification.user_id == user_id))]


def add_salesperson(client, name: str, email: str, **extra) -> int:
    res = login_as(client, ASHA).post("/api/users", json={"full_name": name, "email": email, "password": PASSWORD,
                                                           "role": "Salesperson", **extra})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def ask(client, lead_id: int, reason="I met this customer at the synthetic expo"):
    return client.post(f"/api/leads/{lead_id}/transfer-requests", json={"reason": reason})


def owner_of(lead_id: int) -> int:
    return database().get(Lead, lead_id).owner_id


def test_request_needs_the_owners_approval(client):
    lead = new_lead(login_as(client, PRIYA), "mira@brightline.test")  # Priya's lead
    login_as(client, RAVI)
    assert ask(client, lead["id"], reason="").status_code == 422  # a reason is required
    res = ask(client, lead["id"])
    assert res.status_code == 201, res.text
    request = res.json()
    assert request["status"] == "Pending" and request["owner_name"] == "Priya Sharma" and request["can_cancel"]
    assert owner_of(lead["id"]) == PRIYA  # nothing moves before it is approved
    assert ask(client, lead["id"]).status_code == 409  # asked already
    # the owner and the Admin are asked
    assert "Lead transfer requested" in titles(PRIYA) and "Lead transfer requested" in titles(ASHA)
    # the requester can't approve their own request
    assert client.post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 403
    assert [r["id"] for r in client.get("/api/transfer-requests?box=mine").json()] == [request["id"]]

    login_as(client, PRIYA)
    waiting = client.get("/api/transfer-requests?box=to_approve").json()
    assert [r["id"] for r in waiting] == [request["id"]] and waiting[0]["can_decide"]
    res = client.post(f"/api/transfer-requests/{request['id']}/approve", json={"note": "Ravi knows them"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Approved" and res.json()["decided_by_name"] == "Priya Sharma"
    assert owner_of(lead["id"]) == RAVI
    transfer = database().scalars(select(LeadTransfer).where(LeadTransfer.lead_id == lead["id"])).one()
    assert (transfer.from_user_id, transfer.to_user_id, transfer.transferred_by_id) == (PRIYA, RAVI, PRIYA)
    assert "Transfer request approved by Priya Sharma" in transfer.note
    assert "Lead assigned to you" in titles(RAVI)
    assert client.post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 400  # decided already


def test_rejecting_needs_a_reason_and_keeps_the_lead(client):
    lead = new_lead(login_as(client, PRIYA), "mira@brightline.test")
    request = ask(login_as(client, RAVI), lead["id"]).json()
    admin = login_as(client, ASHA)
    assert admin.post(f"/api/transfer-requests/{request['id']}/reject", json={}).status_code == 422
    res = admin.post(f"/api/transfer-requests/{request['id']}/reject", json={"note": "Priya is mid-demo"})
    assert res.status_code == 200 and res.json()["status"] == "Rejected"
    assert owner_of(lead["id"]) == PRIYA and "Lead transfer request rejected" in titles(RAVI)


def test_the_owners_manager_approves_and_others_cannot(client):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    neha = add_salesperson(client, "Neha Iyer", "neha@crm.test")
    lead = new_lead(login_as(client, RAVI), "mira@brightline.test")  # Ravi's lead; Ravi reports to Priya
    request = ask(login_as(client, neha), lead["id"]).json()
    assert "Lead transfer requested" in titles(PRIYA)  # Ravi's Manager is asked too
    other = add_salesperson(client, "Om Patel", "om@crm.test")
    assert login_as(client, other).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 403
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 200
    assert owner_of(lead["id"]) == neha


def test_approving_closes_other_requests_and_cancel(client):
    neha = add_salesperson(client, "Neha Iyer", "neha@crm.test")
    lead = new_lead(login_as(client, PRIYA), "mira@brightline.test")
    first = ask(login_as(client, RAVI), lead["id"]).json()
    second = ask(login_as(client, neha), lead["id"]).json()
    assert login_as(client, RAVI).post(f"/api/transfer-requests/{second['id']}/cancel").status_code == 403  # not his
    login_as(client, PRIYA).post(f"/api/transfer-requests/{first['id']}/approve", json={})
    mine = login_as(client, neha).get("/api/transfer-requests?box=mine").json()
    assert mine[0]["status"] == "Rejected" and "transferred to Ravi Kumar" in mine[0]["decision_note"]
    # a new request, cancelled by the person who asked
    third = ask(client, lead["id"]).json()  # Neha asks Ravi (the new owner) now
    assert client.post(f"/api/transfer-requests/{third['id']}/cancel").json()["status"] == "Cancelled"


def test_who_cannot_ask(client):
    lead = new_lead(login_as(client, RAVI), "mira@brightline.test")
    assert ask(client, lead["id"]).status_code == 400  # already yours
    assert ask(login_as(client, ASHA), lead["id"]).status_code == 400  # the Admin transfers directly
    db = database()
    db.execute(update(Lead).where(Lead.id == lead["id"]).values(stage="Lost", lost_reason="Price"))
    db.commit()
    res = ask(login_as(client, PRIYA), lead["id"])  # closed leads can't be asked for
    assert res.status_code == 400 and "only open leads" in res.json()["detail"]


def test_a_salesperson_can_ask_for_a_lead_they_cannot_open(client):
    """The "email already in the CRM" message gives the lead's id: the request works without seeing the lead."""
    lead = new_lead(login_as(client, PRIYA), "mira@brightline.test")
    login_as(client, RAVI)
    assert client.get(f"/api/leads/{lead['id']}").status_code == 404  # Ravi can't open Priya's lead
    dup = client.get("/api/leads/duplicates", params={"email": "mira@brightline.test"}).json()
    assert dup["matches"][0]["id"] == lead["id"] and not dup["matches"][0]["can_open"]
    request = ask(client, lead["id"]).json()
    assert request["status"] == "Pending" and not request["can_open_lead"]
    assert [r["id"] for r in client.get(f"/api/leads/{lead['id']}/transfer-requests").json()] == [request["id"]]


def test_lead_list_shows_created_by_and_transferred_to(client):
    lead = new_lead(login_as(client, PRIYA), "mira@brightline.test")
    client.post(f"/api/leads/{lead['id']}/transfer", json={"to_user_id": RAVI, "note": "Synthetic handover"})
    rows = client.get("/api/leads/page", params={"view": "all"}).json()["items"]
    row = next(r for r in rows if r["id"] == lead["id"])
    assert row["created_by_name"] == "Priya Sharma" and row["owner_name"] == "Ravi Kumar"
    assert row["last_transferred_to"] == "Ravi Kumar" and row["last_transferred_at"]
    for sort in ("created_by", "transferred"):
        res = client.get("/api/leads/page", params={"view": "all", "sort": sort})
        assert res.status_code == 200 and res.json()["total"] >= 1
