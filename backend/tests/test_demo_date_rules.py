"""Demo dates use one business time zone, IST (Asia/Kolkata, UTC+05:30), whatever the server's TZ:
- Change Stage > Demo, Edit Lead and Reschedule refuse a time that isn't in the future (the API's now()), read a time
  without an offset as IST, convert a time with an offset, and change nothing when they refuse.
- Times are stored as before (no zone, server time), so older demo dates keep their meaning; the API also sends each
  demo as a UTC instant (demo_at).
All data is made up; each test has its own in-memory database."""
from datetime import datetime, timedelta, timezone

import pytest

from app.assistant import _lead_row, fill_defaults
from app.database import get_db
from app.main import app
from app.models import Lead
from app.services import BUSINESS_TIMEZONE, DEMO_IN_PAST, demo_input, demo_instant, demo_text, now

TASK = {"title": "Synthetic demo follow-up", "due_date": "2030-01-15T10:00:00"}
NOTE = "Synthetic stage note"
NEW_YORK = datetime(2026, 12, 1, 12).astimezone().utcoffset() == timedelta(hours=-5) and \
    datetime(2027, 7, 1, 12).astimezone().utcoffset() == timedelta(hours=-4)
needs_new_york = pytest.mark.skipif(not NEW_YORK, reason="the API runs with TZ=America/New_York (docker-compose.yml)")


def ist(delta=timedelta(0)) -> str:
    """Now (+ delta) as people type it in IST, without an offset: "2026-11-10T07:16:00"."""
    return (datetime.now(BUSINESS_TIMEZONE) + delta).replace(microsecond=0, tzinfo=None).isoformat()


def new_lead(client, name="Demo"):
    res = client.post("/api/leads", json={"first_name": "Test", "source": "Website", "last_name": name, "company": f"{name} Synthetic Co"})
    assert res.status_code == 201, res.text
    return res.json()


def to_demo(client, lead_id, demo_date, **extra):
    body = {"stage": "Demo", "note": NOTE, "task": TASK, "completed_stages": ["Nurturing"], "demo_date": demo_date, **extra}
    return client.put(f"/api/leads/{lead_id}/stage", json=body)


def history(client, lead_id):
    return [h["to_stage"] for h in client.get(f"/api/leads/{lead_id}/history").json()]


def booked_lead(client, name="Booked"):
    lead = new_lead(client, name)
    res = to_demo(client, lead["id"], ist(timedelta(days=5)))
    assert res.status_code == 200, res.text
    return res.json()


def set_demo_date(lead_id, value):
    """Put a demo date on a lead directly, as older data has it (server time, no zone)."""
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, lead_id).demo_date = value
    db.commit()
    db.close()


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---------- Change Stage > Demo ----------

@pytest.mark.parametrize("when", [timedelta(days=-1), timedelta(hours=-2), timedelta(seconds=-30), timedelta(0)])
def test_moving_to_demo_refuses_a_time_that_is_not_in_the_future_and_changes_nothing(client, when):
    lead = new_lead(client)
    before = client.get(f"/api/leads/{lead['id']}").json()
    res = to_demo(client, lead["id"], ist(when))
    assert res.status_code == 400 and res.json()["detail"] == DEMO_IN_PAST
    after = client.get(f"/api/leads/{lead['id']}").json()
    assert after["stage"] == "New" and after["demo_date"] is None
    assert [t["title"] for t in after["tasks"]] == [t["title"] for t in before["tasks"]]  # no task added or closed
    assert history(client, lead["id"]) == ["New"]  # no stage change recorded


def test_moving_to_demo_accepts_a_future_ist_time_and_keeps_the_rules_for_notes_and_tasks(client):
    lead = new_lead(client)
    in_two_days = ist(timedelta(days=2))
    no_task = client.put(f"/api/leads/{lead['id']}/stage", json={
        "stage": "Demo", "note": NOTE, "completed_stages": ["Nurturing"], "demo_date": in_two_days})
    assert no_task.status_code == 422  # the New Task is still required
    no_note = client.put(f"/api/leads/{lead['id']}/stage", json={
        "stage": "Demo", "task": TASK, "completed_stages": ["Nurturing"], "demo_date": in_two_days})
    assert no_note.status_code == 422  # and the note
    soon = ist(timedelta(minutes=2))
    res = to_demo(client, lead["id"], soon)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "Demo"
    # the same moment: what was typed in IST, what is stored in server time, and the UTC instant
    typed = datetime.fromisoformat(soon).replace(tzinfo=BUSINESS_TIMEZONE)
    assert utc(body["demo_at"]) == typed
    assert datetime.fromisoformat(body["demo_date"]) == typed.astimezone().replace(tzinfo=None)


def test_moving_to_demo_without_a_date_still_works(client):
    lead = new_lead(client)
    res = to_demo(client, lead["id"], None)
    assert res.status_code == 200 and res.json()["demo_date"] is None and res.json()["demo_at"] is None


@needs_new_york
@pytest.mark.parametrize("sent, stored, instant", [
    ("2030-12-01T15:00:00", "2030-12-01T04:30:00", "2030-12-01T09:30:00Z"),        # no offset: IST
    ("2030-12-01T15:00:00+05:30", "2030-12-01T04:30:00", "2030-12-01T09:30:00Z"),  # IST written out
    ("2030-12-01T15:00:00Z", "2030-12-01T10:00:00", "2030-12-01T15:00:00Z"),       # UTC, New York winter (EST)
    ("2030-07-01T15:00:00Z", "2030-07-01T11:00:00", "2030-07-01T15:00:00Z"),       # UTC, New York summer (EDT)
    ("2030-03-10T12:00:00", "2030-03-10T01:30:00", "2030-03-10T06:30:00Z"),        # IST noon: New York before its change
    ("2030-03-10T13:00:00", "2030-03-10T03:30:00", "2030-03-10T07:30:00Z"),        # an hour later: after it (02:30 is skipped)
])
def test_demo_times_are_ist_and_stored_in_server_time(client, sent, stored, instant):
    lead = new_lead(client)
    res = to_demo(client, lead["id"], sent)
    assert res.status_code == 200, res.text
    assert res.json()["demo_date"] == stored and res.json()["demo_at"] == instant


@needs_new_york
def test_known_limit_new_yorks_repeated_hour_cannot_be_told_apart_in_storage():
    """11:00 and 12:00 IST on 3 Nov 2030 are both 01:30 in New York (clocks go back there): stored without a zone
    they look the same, and both read back as the first one. Only a change to how times are stored fixes this."""
    first, second = demo_input(datetime(2030, 11, 3, 11)), demo_input(datetime(2030, 11, 3, 12))
    assert first == second == datetime(2030, 11, 3, 1, 30)
    assert demo_instant(second) == datetime(2030, 11, 3, 5, 30, tzinfo=timezone.utc)  # 11:00 IST, not 12:00


def test_an_offset_cannot_slip_a_past_time_through(client):
    lead = new_lead(client)
    an_hour_ago_utc = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    assert to_demo(client, lead["id"], an_hour_ago_utc).status_code == 400


# ---------- older demo dates keep their meaning ----------

@needs_new_york
def test_an_older_demo_date_keeps_its_server_time_meaning_and_is_shown_in_ist(client):
    lead = new_lead(client)
    set_demo_date(lead["id"], datetime(2026, 11, 20, 10, 30))  # saved before, in server time (New York)
    body = client.get(f"/api/leads/{lead['id']}").json()
    assert body["demo_date"] == "2026-11-20T10:30:00"  # not rewritten
    assert body["demo_at"] == "2026-11-20T15:30:00Z"  # the same moment
    assert demo_text(datetime(2026, 11, 20, 10, 30)) == "20 Nov 2026 09:00 PM IST"  # how messages show it


# ---------- Edit Lead ----------

def test_edit_lead_refuses_moving_the_demo_into_the_past(client):
    lead = booked_lead(client)
    res = client.put(f"/api/leads/{lead['id']}", json={"demo_date": ist(timedelta(hours=-1)), "title": "Changed"})
    assert res.status_code == 400 and res.json()["detail"] == DEMO_IN_PAST
    after = client.get(f"/api/leads/{lead['id']}").json()
    assert after["demo_date"] == lead["demo_date"] and after["title"] != "Changed"  # nothing saved


def test_edit_lead_accepts_a_future_demo_and_keeps_a_past_one_that_is_not_changed(client):
    lead = booked_lead(client)
    later = ist(timedelta(days=9))
    moved = client.put(f"/api/leads/{lead['id']}", json={"demo_date": later})
    assert moved.status_code == 200
    assert utc(moved.json()["demo_at"]) == datetime.fromisoformat(later).replace(tzinfo=BUSINESS_TIMEZONE)
    # a demo that has already passed: the lead's other details can still be saved, the form sending the same moment
    # back in IST (with or without the offset)
    past = (now() - timedelta(days=3)).replace(second=0)
    set_demo_date(lead["id"], past)
    same_in_ist = demo_instant(past).astimezone(BUSINESS_TIMEZONE)
    for sent in (same_in_ist.isoformat(), same_in_ist.replace(tzinfo=None).isoformat()):
        res = client.put(f"/api/leads/{lead['id']}", json={"demo_date": sent, "title": "Still editable"})
        assert res.status_code == 200, res.text
        assert res.json()["title"] == "Still editable" and res.json()["demo_date"] == past.isoformat()
    # but not move it to another past time
    other = (same_in_ist - timedelta(days=1)).isoformat()
    assert client.put(f"/api/leads/{lead['id']}", json={"demo_date": other}).status_code == 400


def test_edit_lead_can_still_clear_the_demo_date(client):
    lead = booked_lead(client)
    res = client.put(f"/api/leads/{lead['id']}", json={"demo_date": None})
    assert res.status_code == 200 and res.json()["demo_date"] is None


def test_a_manager_editing_someone_elses_lead_follows_the_same_rule(client):
    from conftest import login_as
    lead = booked_lead(client)  # Ravi's lead (Salesperson)
    login_as(client, 1)  # Priya, Manager: may edit team records
    assert client.put(f"/api/leads/{lead['id']}", json={"demo_date": ist(timedelta(days=-1))}).status_code == 400
    assert client.put(f"/api/leads/{lead['id']}", json={"demo_date": ist(timedelta(days=4))}).status_code == 200


# ---------- Reschedule ----------

@pytest.mark.parametrize("when", [timedelta(days=-1), timedelta(hours=-2), timedelta(0)])
def test_reschedule_refuses_a_time_that_is_not_in_the_future(client, when):
    lead = booked_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reschedule_to": ist(when)})
    assert res.status_code == 400 and res.json()["detail"] == "Choose a new demo date and time in the future"
    assert client.get(f"/api/leads/{lead['id']}").json()["demo_date"] == lead["demo_date"]


@needs_new_york
def test_reschedule_reads_ist_and_says_so_in_the_history(client):
    lead = booked_lead(client)
    res = client.post(f"/api/leads/{lead['id']}/cancel-demo", json={"reschedule_to": "2030-12-01T15:00:00"})
    assert res.status_code == 200, res.text
    assert res.json()["stage"] == "Demo" and res.json()["demo_at"] == "2030-12-01T09:30:00Z"
    notes = [h["note"] for h in client.get(f"/api/leads/{lead['id']}/history").json()]
    assert "Demo rescheduled to 01 Dec 2030 03:00 PM IST" in notes


# ---------- Home: Today's Events is the IST day ----------

def test_todays_events_lists_the_demos_on_todays_ist_date(client):
    ist_now = datetime.now(BUSINESS_TIMEZONE)
    if ist_now.hour >= 23:
        pytest.skip("too close to midnight in IST to book a demo later today")
    later_today = ist_now.replace(hour=23, minute=30, second=0, microsecond=0)
    lead = new_lead(client, "Tonight")
    assert to_demo(client, lead["id"], later_today.replace(tzinfo=None).isoformat()).status_code == 200
    events = client.get("/api/home").json()["seller_home"]["todays_events"]
    mine = [e for e in events if e["lead_id"] == lead["id"]]
    assert len(mine) == 1 and utc(mine[0]["start_at"]) == later_today


# ---------- AI Assistant: demo times in IST (no AI call: the helpers only) ----------

@needs_new_york
def test_assistant_booking_keeps_the_demo_task_on_the_demo_and_says_ist():
    args = fill_defaults(None, "move_lead_stage", {"lead_id": None, "stage": "Demo", "demo_date": "2030-12-01T15:00"})
    assert args["task_due_date"] == "2030-12-01T04:30:00"  # the demo moment in server time, like the demo itself
    assert args["note"] == "Demo booked for 01 Dec 2030, 03:00 PM IST."
    row = _lead_row({"id": 1, "name": "x", "demo_date": "2030-12-01T04:30:00", "demo_at": "2030-12-01T09:30:00Z"})
    assert row["demo_date"] == "2030-12-01T15:00+05:30"
