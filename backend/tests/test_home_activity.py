"""Home > Plan Accounts, Grow Relationships and Build Pipeline: the Upcoming / Past / No Activity pills.
Each pill opens the list with exactly the records it counts (one rule: services.activity_condition).
All data is made up."""
from datetime import datetime, timedelta

from sqlalchemy import delete, update

from app.database import get_db
from app.main import app
from app.models import Lead, Task
from test_opportunity_duplicates import create, new_lead


def session():
    return next(app.dependency_overrides[get_db]())


def pills(card):
    return card["upcoming_activity"], card["past_activity"], card["no_activity"]


def test_build_pipeline_pills_open_the_leads_they_count(client):
    upcoming = new_lead(client, "mira@brightline.test")  # new leads get "Make first contact", due tomorrow
    past = new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao")
    none = new_lead(client, "lena@northwind.test", company="Northwind Traders", first="Lena", last="Park")
    db = session()
    db.execute(update(Task).where(Task.lead_id == past["id"]).values(status="Completed"))  # only finished tasks
    db.execute(delete(Task).where(Task.lead_id == none["id"]))  # no tasks at all (like uploaded leads)
    old = new_lead(client, "old@archive.test", company="Archive Co", first="Old", last="Lead")
    db.execute(update(Lead).where(Lead.id == old["id"]).values(created_at=datetime.now() - timedelta(days=45)))
    db.commit()

    card = client.get("/api/home").json()["seller_home"]["build_pipeline"]
    assert card["leads_last_30_days"] == 3  # the 45-day-old lead isn't counted
    assert pills(card) == (1, 1, 1)
    for activity, lead in (("upcoming", upcoming), ("past", past), ("none", none)):
        page = client.get("/api/leads/page", params={"view": "my", "activity": activity, "created_days": 30}).json()
        assert [r["id"] for r in page["items"]] == [lead["id"]], activity
        assert page["total"] == 1
    assert client.get("/api/leads/page", params={"activity": "soon"}).status_code == 400


def test_account_and_contact_pills_match_the_lists(client):
    live = create(client, name="Brightline rollout", account_name="Brightline Logistics", contact_last_name="Shah").json()
    done = create(client, name="Harbor pilot", account_name="Harbor Freight Labs", contact_last_name="Rao").json()
    res = client.post("/api/accounts", json={"name": "Northwind Traders", "industry": "Retail", "phone": "+1 415 555 0101"})
    assert res.status_code == 201, res.text  # no deals: no activity
    db = session()
    db.execute(update(Task).where(Task.opportunity_id == done["opportunity"]["id"]).values(status="Completed"))
    db.commit()

    home = client.get("/api/home").json()["seller_home"]
    accounts, contacts = client.get("/api/accounts").json(), client.get("/api/contacts").json()
    for card, rows in ((home["accounts"], accounts), (home["contacts"], contacts)):
        listed = tuple(sum(r["activity"] == a for r in rows) for a in ("upcoming", "past", "none"))
        assert pills(card) == listed and card["total"] == len(rows)
    by_name = {a["name"]: a["activity"] for a in accounts}
    assert by_name == {"Brightline Logistics": "upcoming", "Harbor Freight Labs": "past", "Northwind Traders": "none"}
    assert {c["last_name"]: c["activity"] for c in contacts} == {"Shah": "upcoming", "Rao": "past"}
