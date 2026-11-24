"""Leads > Deleted Leads: a deleted lead is kept as a copy and can be restored (one, several or all) to the Unassigned
Pool with its fields and notes. The Admin sees all of them, a Manager their own, their team's and pooled ones;
Salespeople can't see or restore them. Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin), plus the
people added below. All data is made up."""
import itertools

from app.database import get_db
from app.main import app
from app.models import DeletedLead, Lead, User
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3
EMAILS = itertools.count(1)


def db():
    return next(app.dependency_overrides[get_db]())


def add_user(full_name, email, role, **fields) -> int:
    with db() as s:
        user = User(full_name=full_name, email=email, role=role, password_hash="x", **fields)
        s.add(user)
        s.commit()
        return user.id


def new_lead(client, name="Lopez", **fields):
    body = {"first_name": "Test", "last_name": name, "company": "Bluebird", "source": "Website",
            "email": f"{name.lower()}{next(EMAILS)}@bluebird.example", **fields}
    res = client.post("/api/leads", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def deleted(client, **params):
    res = client.get("/api/deleted-leads", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_deleted_lead_is_kept_and_restored_to_the_unassigned_pool_with_its_notes(client):
    login_as(client, ASHA)
    lead = new_lead(client, "Fernandes", owner_id=RAVI, title="Synthetic Buyer", annual_revenue=125000.5)
    assert client.post("/api/notes", json={"lead_id": lead["id"], "body": "Synthetic call note"}).status_code in (200, 201)
    assert client.delete(f"/api/leads/{lead['id']}").status_code == 200
    assert client.get(f"/api/leads/{lead['id']}").status_code == 404

    items = deleted(client)
    assert items["total"] == 1
    row = items["items"][0]
    assert row["name"] == "Test Fernandes" and row["owner_name"] == "Ravi Kumar" and row["deleted_by_name"] == "Asha Rao"
    assert row["lead_id"] == lead["id"]

    res = client.post("/api/deleted-leads/restore", json={"ids": [row["id"]]}).json()
    assert res["restored"] == [{"id": lead["id"], "name": "Test Fernandes"}] and res["skipped"] == []
    back = client.get(f"/api/leads/{lead['id']}").json()  # the same id, so old links work again
    assert back["owner_id"] is None and back["title"] == "Synthetic Buyer" and back["email"] == lead["email"]
    assert float(back["annual_revenue"]) == 125000.5
    with db() as s:
        restored = s.get(Lead, lead["id"])
        bodies = [n.body for n in restored.notes]
        assert restored.assigned_at is None and restored.created_at is not None
    assert "Synthetic call note" in bodies and any(b.startswith("Restored from Deleted Leads by Asha Rao") for b in bodies)
    assert deleted(client)["total"] == 0
    pool = client.get("/api/leads/page", params={"view": "unassigned"}).json()
    assert lead["id"] in [x["id"] for x in pool["items"]]
    log = client.get("/api/activity-log").json()
    assert any(r["action"] == "Lead restored" and r["target"] == "Test Fernandes" for r in log)


def test_bulk_delete_keeps_every_lead_and_several_are_restored_at_once(client):
    login_as(client, ASHA)
    leads = [new_lead(client, name) for name in ("Alpha", "Bravo", "Charlie")]
    res = client.post("/api/leads/bulk-delete", json={"lead_ids": [x["id"] for x in leads]}).json()
    assert res["deleted"] == 3
    rows = deleted(client)["items"]
    assert len(rows) == 3
    res = client.post("/api/deleted-leads/restore", json={"ids": [r["id"] for r in rows] + [rows[0]["id"], 99999]}).json()
    assert len(res["restored"]) == 3  # a repeated id is restored once
    assert res["skipped"] == [{"id": 99999, "name": None, "reason": "already restored or expired"}]
    for item in leads:
        assert client.get(f"/api/leads/{item['id']}").json()["owner_id"] is None


def test_a_lead_whose_email_is_on_another_lead_is_skipped(client):
    login_as(client, ASHA)
    lead = new_lead(client, "Duplicate")
    client.delete(f"/api/leads/{lead['id']}")
    with db() as s:  # someone added the same person again
        s.add(Lead(first_name="Again", last_name="Added", email=lead["email"].upper(), source="Website"))
        s.commit()
    row = deleted(client)["items"][0]
    res = client.post("/api/deleted-leads/restore", json={"ids": [row["id"]]}).json()
    assert res["restored"] == [] and res["skipped"][0]["reason"] == "email used by Again Added" and "email used by" in res["skipped"][0]["reason"]
    assert deleted(client)["total"] == 1  # stays in Deleted Leads


def test_the_old_id_is_reused_only_when_free(client):
    login_as(client, ASHA)
    lead = new_lead(client, "Moved")
    client.delete(f"/api/leads/{lead['id']}")
    with db() as s:
        s.add(Lead(id=lead["id"], first_name="Took", last_name="Id", email="took.id@bluebird.example", source="Website"))
        s.commit()
    res = client.post("/api/deleted-leads/restore", json={"ids": [deleted(client)["items"][0]["id"]]}).json()
    assert res["restored"][0]["id"] != lead["id"]
    assert client.get(f"/api/leads/{res['restored'][0]['id']}").json()["last_name"] == "Moved"


def test_who_sees_and_restores_deleted_leads(client):
    other_manager = add_user("Neha Iyer", "neha@crm.test", "Manager")
    ravi_team = add_user("Kiran Das", "kiran@crm.test", "Salesperson", reports_to_id=PRIYA)
    neha_team = add_user("Arjun Pillai", "arjun@crm.test", "Salesperson", reports_to_id=other_manager)
    login_as(client, ASHA)
    mine = new_lead(client, "Team", owner_id=ravi_team)
    theirs = new_lead(client, "Other", owner_id=neha_team)
    pooled = new_lead(client, "Pooled")
    for item in (mine, theirs, pooled):
        assert client.delete(f"/api/leads/{item['id']}").status_code == 200
        if item is pooled:
            with db() as s:  # a pooled lead has no owner
                s.query(DeletedLead).filter_by(lead_id=item["id"]).update({"owner_id": None, "owner_name": None})
                s.commit()

    assert deleted(client)["total"] == 3  # the Admin sees all
    names = {r["name"] for r in deleted(login_as(client, PRIYA))["items"]}
    assert names == {"Test Team", "Test Pooled"}  # Priya: her team's and pooled ones, not Neha's team's
    assert deleted(client, search="pool")["total"] == 1
    hidden = next(r for r in deleted(login_as(client, ASHA))["items"] if r["name"] == "Test Other")
    res = login_as(client, PRIYA).post("/api/deleted-leads/restore", json={"ids": [hidden["id"]]}).json()
    assert res["restored"] == [] and len(res["skipped"]) == 1

    login_as(client, RAVI)
    assert client.get("/api/deleted-leads").status_code == 403
    assert client.post("/api/deleted-leads/restore", json={"ids": [hidden["id"]]}).status_code == 403
    assert client.post("/api/deleted-leads/restore", json={"ids": []}).status_code == 422


def test_paging(client):
    login_as(client, ASHA)
    for name in ("One", "Two", "Three"):
        client.delete(f"/api/leads/{new_lead(client, name)['id']}")
    first = deleted(client, page=1, page_size=2)
    second = deleted(client, page=2, page_size=2)
    assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
    assert first["items"][0]["name"] == "Test Three"  # newest first


def test_a_deleted_lead_can_be_restored_for_90_days_then_it_is_deleted_for_good(client):
    from datetime import timedelta

    from app import scheduler
    from app.services import now

    login_as(client, ASHA)
    old, recent, last_day = (new_lead(client, name) for name in ("Old", "Recent", "Lastday"))
    for item in (old, recent, last_day):
        client.delete(f"/api/leads/{item['id']}")
    with db() as s:  # deleted 91, 10 and 90 days ago
        for item, days in ((old, 91), (recent, 10), (last_day, 89)):
            s.query(DeletedLead).filter_by(lead_id=item["id"]).update({"deleted_at": now() - timedelta(days=days)})
        s.commit()
    with db() as s:
        stale = s.query(DeletedLead).filter_by(lead_id=old["id"]).one().id
    rows = {r["name"]: r for r in deleted(client)["items"]}  # the list never shows one past 90 days
    assert set(rows) == {"Test Recent", "Test Lastday"}
    assert rows["Test Recent"]["days_left"] == 80 and rows["Test Lastday"]["days_left"] == 1
    assert deleted(client)["keep_days"] == 90
    res = client.post("/api/deleted-leads/restore", json={"ids": [stale]}).json()
    assert res["restored"] == [] and res["skipped"][0]["reason"] == "already restored or expired"

    with db() as s:  # the background checks delete them for good
        s.query(DeletedLead).filter_by(lead_id=recent["id"]).update({"deleted_at": now() - timedelta(days=95)})
        s.commit()
        scheduler.run_checks(s)
        assert {r.lead_id for r in s.query(DeletedLead).all()} == {last_day["id"]}
