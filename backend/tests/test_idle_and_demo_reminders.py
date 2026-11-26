"""Reminders: (1) open leads and opportunities with no update or activity for 3+ days get one daily summary for the
owner, their Manager and the Admin; (2) a demo's reminders stop once the demo time has passed (the task shows as
overdue, but no bell reminder or email). Users: 1 Priya (Manager), 2 Ravi (Salesperson, set to report to Priya
below), 3 Asha (Admin). All data is made up."""
from datetime import datetime, timedelta

import pytest

from app import idle_reminders, scheduler
from app.database import get_db
from app.main import app
from app.models import Account, Lead, Note, Notification, Opportunity, Task, User
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3
TEN_AM = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
OLD = TEN_AM - timedelta(days=5)


def db():
    return next(app.dependency_overrides[get_db]())


@pytest.fixture
def at_ten(monkeypatch):
    monkeypatch.setattr(idle_reminders, "now", lambda: TEN_AM)
    monkeypatch.setattr(scheduler, "now", lambda: TEN_AM)
    with db() as s:
        s.get(User, RAVI).reports_to_id = PRIYA
        s.commit()


def lead(name, owner=RAVI, stage="New", when=OLD, company="Synthetic Co"):
    with db() as s:
        row = Lead(first_name="Test", last_name=name, company=company, source="Website", stage=stage,
                   owner_id=owner, created_at=when, updated_at=when, assigned_at=when if owner else None)
        s.add(row)
        s.commit()
        return row.id


def opportunity(name, owner=RAVI, stage="Discovery", when=OLD):
    with db() as s:
        account = Account(name=f"{name} Account", owner_id=owner)
        s.add(account)
        s.flush()
        row = Opportunity(name=name, stage=stage, owner_id=owner, account_id=account.id, created_at=when, updated_at=when)
        s.add(row)
        s.commit()
        return row.id


def summaries(user_id):
    with db() as s:
        return [n.message for n in s.query(Notification).filter_by(user_id=user_id, title=idle_reminders.IDLE_TITLE)]


def test_idle_records_get_one_daily_summary_for_owner_manager_and_admin(client, at_ten):
    idle = lead("Idle")
    busy = lead("Busy")
    lead("Pooled", owner=None)  # nobody's to follow up
    lead("Closed", stage="Lost")
    lead("Fresh", when=TEN_AM - timedelta(days=1))
    deal = opportunity("Synthetic Deal")
    with db() as s:  # a note yesterday: not idle
        s.add(Note(lead_id=busy, body="Synthetic call", created_by_id=RAVI, created_at=TEN_AM - timedelta(days=1)))
        s.commit()

    with db() as s:
        assert idle_reminders.send_idle_reminders(s) == 3  # Ravi, Priya (his Manager), Asha (Admin)
        s.commit()
    mine = summaries(RAVI)
    assert len(mine) == 1
    lines = mine[0].split("\n")
    assert lines[0] == "1 lead and 1 opportunity have had no update or activity for 3+ days. Please follow up."
    assert f"Lead: Test Idle (Synthetic Co) · idle since {OLD:%d %b %Y}" in lines  # his own: no owner name
    assert f"Opportunity: Synthetic Deal · idle since {OLD:%d %b %Y}" in lines
    assert "Test Busy" not in mine[0] and "Pooled" not in mine[0] and "Closed" not in mine[0] and "Fresh" not in mine[0]
    assert f"Lead: Test Idle (Synthetic Co) · Owner: Ravi Kumar · idle since {OLD:%d %b %Y}" in summaries(PRIYA)[0]
    assert len(summaries(ASHA)) == 1
    with db() as s:
        sent = s.query(Notification).filter_by(user_id=RAVI, title=idle_reminders.IDLE_TITLE).one()
        assert sent.link == "/leads?list=No%20Activity%20%283%2B%20Days%29"
        # once a day
        assert idle_reminders.send_idle_reminders(s) == 0

    # the list views the summary links to
    login_as(client, ASHA)
    page = client.get("/api/leads/page", params={"view": "idle"}).json()
    assert [r["id"] for r in page["items"]] == [idle]
    opps = {o["id"]: o["idle"] for o in client.get("/api/opportunities").json()}
    assert opps[deal] is True


def test_a_new_day_replaces_the_summary_and_nothing_goes_before_nine(client, at_ten, monkeypatch):
    lead("Waiting")
    with db() as s:
        idle_reminders.send_idle_reminders(s)
        s.commit()
    tomorrow = TEN_AM + timedelta(days=1)
    monkeypatch.setattr(idle_reminders, "now", lambda: tomorrow)
    monkeypatch.setattr(idle_reminders, "start_of_today", lambda: tomorrow.replace(hour=0))
    with db() as s:
        assert idle_reminders.send_idle_reminders(s) == 3
        s.commit()
    assert len(summaries(RAVI)) == 1  # the bell keeps only the latest summary
    monkeypatch.setattr(idle_reminders, "now", lambda: TEN_AM.replace(hour=8) + timedelta(days=2))
    with db() as s:
        assert idle_reminders.send_idle_reminders(s) == 0


def test_activity_of_any_kind_ends_idleness(client, at_ten):
    ids = {name: lead(name) for name in ("Task", "Done", "Edited")}
    with db() as s:
        s.add(Task(title="Call", due_date=TEN_AM, owner_id=RAVI, lead_id=ids["Task"], created_at=TEN_AM - timedelta(hours=2),
                   updated_at=TEN_AM - timedelta(hours=2)))
        s.add(Task(title="Old call", due_date=OLD, owner_id=RAVI, lead_id=ids["Done"], status="Done", created_at=OLD,
                   updated_at=OLD, completed_at=TEN_AM - timedelta(hours=1)))
        s.get(Lead, ids["Edited"]).updated_at = TEN_AM - timedelta(hours=3)
        s.commit()
        assert idle_reminders.send_idle_reminders(s) == 0


def test_a_past_demo_shows_overdue_but_sends_no_more_reminders(client, at_ten):
    demo = lead("Demo", stage="Demo")
    with db() as s:
        past = Task(title="Conduct demo", due_date=TEN_AM - timedelta(days=2), reminder_at=TEN_AM - timedelta(days=2, hours=1),
                    reminder_sent=False, owner_id=RAVI, lead_id=demo, is_auto=True, priority="High")
        prep = Task(title="Prepare for demo", due_date=TEN_AM - timedelta(days=3), owner_id=RAVI, lead_id=demo, is_auto=True)
        follow = Task(title="Follow-up call", due_date=TEN_AM - timedelta(days=2), owner_id=RAVI, lead_id=demo)
        s.add_all([past, prep, follow])
        s.commit()
        # an earlier reminder for the demo, from before it happened
        s.add(Notification(user_id=RAVI, title="Task reminder", message="Conduct demo is due", kind="reminder",
                           task_id=past.id, created_at=TEN_AM - timedelta(days=2, hours=1)))
        s.commit()
        result = scheduler.run_checks(s)
        assert result["reminders"] == 1 and result["overdue"] == 1  # only the ordinary follow-up is chased
        overdue = [n.message for n in s.query(Notification).filter_by(user_id=RAVI, title="Task overdue")]
        assert len(overdue) == 1 and overdue[0].startswith("Follow-up call")
        assert s.get(Task, past.id).reminder_sent is True  # never sent late
        assert s.query(Notification).filter_by(user_id=RAVI, title="Task reminder").count() == 1
        past_id = past.id
    bell = login_as(client, RAVI).get("/api/notifications").json()
    assert all(n.get("task_id") != past_id for n in bell)  # the demo's reminder left the bell
    tasks = client.get("/api/tasks").json()
    assert any(t["title"] == "Conduct demo" and t["status"] == "Open" for t in tasks)  # still shows (overdue) in Tasks


def test_an_upcoming_demo_is_still_reminded(client, at_ten):
    demo = lead("Soon", stage="Demo")
    with db() as s:
        s.add(Task(title="Conduct demo", due_date=TEN_AM + timedelta(minutes=30), reminder_at=TEN_AM - timedelta(minutes=30),
                   owner_id=RAVI, lead_id=demo, is_auto=True))
        s.commit()
        assert scheduler.run_checks(s)["reminders"] == 1
