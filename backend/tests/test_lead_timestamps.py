"""Issue 46: a lead's recorded times (Created, Last Modified, Assigned, Transferred...) are stored in the server's time
zone without a zone, and must reach the browser with that zone's offset, so India and the US see the same moment, each
in their own local time. Stored values never change. Times people type in (the demo date) are sent as before.
Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin). All data is made up."""
import os
import time
from datetime import datetime, timezone

import pytest

from app.database import get_db
from app.main import app
from app.models import Lead
from conftest import login_as

ASHA, RAVI = 3, 2
CREATED, EDITED = datetime(2026, 11, 18, 20, 33, 20), datetime(2026, 11, 18, 20, 34, 51)


@pytest.fixture
def server_zone():
    """Sets the API's time zone (TZ, as docker-compose.yml does) for one test, and puts the old one back."""
    saved = os.environ.get("TZ")

    def use(zone):
        os.environ["TZ"] = zone
        time.tzset()
    yield use
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


def db():
    return next(app.dependency_overrides[get_db]())


def stored(lead_id, **values):
    """Gives a synthetic lead known stored times (server wall clock, no zone); returns what is stored afterwards."""
    with db() as s:
        lead = s.get(Lead, lead_id)
        for name, value in values.items():
            setattr(lead, name, value)
        s.commit()
        return {name: getattr(s.get(Lead, lead_id), name) for name in values}


def new_lead(client):
    res = login_as(client, RAVI).post("/api/leads", json={"first_name": "Tina", "last_name": "Timezonecheck",
                                                           "company": "Timezone Synthetic Co", "source": "Website",
                                                           "email": "tina.tz@timezone-synthetic.example"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def instant(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def test_created_and_last_modified_carry_the_server_offset(client, server_zone):
    server_zone("America/New_York")
    lead_id = new_lead(client)
    assert stored(lead_id, created_at=CREATED, updated_at=EDITED) == {"created_at": CREATED, "updated_at": EDITED}
    ravi = login_as(client, RAVI)
    detail = ravi.get(f"/api/leads/{lead_id}").json()
    assert (detail["created_at"], detail["updated_at"]) == ("2026-11-18T20:33:20-05:00", "2026-11-18T20:34:51-05:00")
    # the same moment for everyone: 01:33:20 UTC on 19 Nov (7:03 AM in India, 8:33 PM in New York)
    assert instant(detail["created_at"]) == datetime(2026, 11, 19, 1, 33, 20, tzinfo=timezone.utc)
    # the Leads list (and so the Kanban) sends the same values; Created and Last Modified stay different
    row = next(l for l in ravi.get("/api/leads/page", params={"view": "my_open"}).json()["items"] if l["id"] == lead_id)
    assert (row["created_at"], row["updated_at"]) == (detail["created_at"], detail["updated_at"])
    # nothing stored was changed by reading it
    with db() as s:
        lead = s.get(Lead, lead_id)
        assert (lead.created_at, lead.updated_at) == (CREATED, EDITED)


def test_the_offset_is_the_servers_own_zone_including_daylight_saving(client, server_zone):
    server_zone("America/New_York")
    lead_id = new_lead(client)
    stored(lead_id, created_at=datetime(2026, 7, 1, 9, 0, 0), updated_at=CREATED)
    detail = login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()
    assert detail["created_at"] == "2026-07-01T09:00:00-04:00"  # summer time in New York
    # a server running in India would send its own offset (nothing is hard-coded)
    server_zone("Asia/Kolkata")
    detail = login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()
    assert detail["updated_at"] == "2026-11-18T20:33:20+05:30"


def test_assignment_and_transfer_times_match_last_modified_and_typed_times_are_unchanged(client, server_zone):
    server_zone("America/New_York")
    lead_id = new_lead(client)
    assert login_as(client, ASHA).post(f"/api/leads/{lead_id}/transfer", json={"to_user_id": 1}).status_code == 200
    detail = login_as(client, ASHA).get(f"/api/leads/{lead_id}").json()
    for field in ("created_at", "updated_at", "assigned_at", "owner_since", "last_transferred_at"):
        assert detail[field][-6:] in ("-05:00", "-04:00"), (field, detail[field])
    assert detail["transfers"][0]["transferred_at"][-6:] in ("-05:00", "-04:00")
    assert detail["owner_since"] == detail["assigned_at"]
    # a demo date is what the person typed (sent as before, with demo_at for the moment)
    stored(lead_id, demo_date=datetime(2026, 12, 1, 15, 0, 0))
    detail = login_as(client, ASHA).get(f"/api/leads/{lead_id}").json()
    assert detail["demo_date"] == "2026-12-01T15:00:00"


def test_each_value_gets_its_own_dates_offset_and_converts_to_india_time(client, server_zone):
    """The offset comes from the zone's rule for the value's date, never from today's offset (today can be either
    season: New York is in standard time in November while Sydney is in daylight time)."""
    from zoneinfo import ZoneInfo
    india = ZoneInfo("Asia/Kolkata")
    server_zone("America/New_York")
    lead_id = new_lead(client)
    for value, sent, in_india in (
            (datetime(2024, 8, 15, 14, 5), "2024-08-15T14:05:00-04:00", "2024-08-15 23:35"),  # historical summer
            (datetime(2025, 1, 20, 23, 30), "2025-01-20T23:30:00-05:00", "2025-01-21 10:00"),  # historical winter
            (datetime(2026, 7, 1, 9, 0), "2026-07-01T09:00:00-04:00", "2026-07-01 18:30")):  # this summer
        stored(lead_id, created_at=value)
        got = login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()["created_at"]
        assert got == sent
        assert datetime.fromisoformat(got).astimezone(india).strftime("%Y-%m-%d %H:%M") == in_india
    server_zone("Australia/Sydney")  # opposite hemisphere: winter in July, summer in November
    stored(lead_id, created_at=datetime(2026, 7, 1, 9, 0), updated_at=datetime(2026, 11, 18, 9, 0))
    detail = login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()
    assert (detail["created_at"][-6:], detail["updated_at"][-6:]) == ("+10:00", "+11:00")


def test_daylight_saving_edges_are_read_as_documented(client, server_zone):
    """Stored values have no zone, so New York's repeated autumn hour can't be told apart: it is read as the first one
    (daylight time). Values in the skipped spring hour never come from the clock and are read as standard time."""
    server_zone("America/New_York")
    lead_id = new_lead(client)
    for value, sent in ((datetime(2026, 11, 1, 0, 59), "2026-11-01T00:59:00-04:00"),
                        (datetime(2026, 11, 1, 1, 30), "2026-11-01T01:30:00-04:00"),  # happens twice: the first one
                        (datetime(2026, 11, 1, 2, 0), "2026-11-01T02:00:00-05:00"),
                        (datetime(2026, 3, 8, 1, 59), "2026-03-08T01:59:00-05:00"),
                        (datetime(2026, 3, 8, 3, 0), "2026-03-08T03:00:00-04:00")):
        stored(lead_id, created_at=value)
        assert login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()["created_at"] == sent
    stored(lead_id, created_at=datetime(2026, 3, 8, 2, 30))  # doesn't exist on a New York clock
    got = login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()["created_at"]
    assert instant(got) == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)  # = 02:30 standard time = 03:30 daylight
