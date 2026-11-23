"""Issue 6: the AI Assistant counts leads assigned from the Unassigned Pool (assignment_report), by WHEN they were
assigned (each lead's Transfer History), in IST days, never from creation dates or who owns a lead now.

The model is scripted (no AI service): each test makes the stand-in call the tool, and checks what the tool gave it.
The server clock is New York (docker-compose.yml TZ), as in the app: stored times are New York times.
Users: 1 Priya (Manager: Ravi, Tara and Sai report to her), 2 Ravi, 3 Asha (Admin). All data is made up."""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import assistant
from app.assistant_reports import ist_to_server
from app.models import Lead, LeadTransfer
from app.services import BUSINESS_TIMEZONE
from conftest import login_as
from test_assistant import ai, call  # noqa: F401
from test_unassigned_pool import ASHA, PRIYA, RAVI, REASON, add_user, db, pool_rows, pooled_ids, team, upload  # noqa: F401


@pytest.fixture
def sai(client, team, monkeypatch):
    """Sai, a Salesperson in Priya's team; the server clock is New York's, as in docker-compose.yml."""
    monkeypatch.setenv("TZ", "America/New_York")
    return add_user("Sai Kiran", "sai@crm.test", "Salesperson", reports_to_id=PRIYA)


def stamp(lead_ids, when: datetime, *, created: datetime | None = None):
    """Their pool assignment happened at `when` (server time, as stored); optionally they were created earlier."""
    with db() as s:
        for move in s.query(LeadTransfer).filter(LeadTransfer.lead_id.in_(lead_ids)):
            move.transferred_at = when
        if created:
            for lead in s.query(Lead).filter(Lead.id.in_(lead_ids)):
                lead.created_at = created
        s.commit()


def tool(client, ai, user_id, name="assignment_report", **args):  # noqa: F811
    """The scripted model calls one tool with these arguments; returns exactly what the tool gave the model."""
    script, seen = ai
    script += [[call(name, **args)], "Scripted answer."]
    res = login_as(client, user_id).post("/api/assistant/chat", json={"message": "How many pooled leads were assigned?"})
    assert res.status_code == 200, res.text
    return json.loads(seen[-1][-1]["content"])


def pool(client, n, prefix):
    upload(login_as(client, ASHA), pool_rows(n, prefix=prefix))
    return sorted(pooled_ids(client))[-n:]


def test_seven_pool_assignments_on_the_incident_day_are_counted_by_when_they_were_assigned(client, sai, ai):
    ids = pool(client, 7, "Incident")
    assert login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": ids, "to_user_id": sai}).json()["assigned"] == 7
    # 20 Nov 2026, 6:21 PM IST = 7:51 AM in New York; the leads were uploaded two days earlier
    stamp(ids, datetime(2026, 11, 20, 7, 51), created=datetime(2026, 11, 18, 9, 0))
    day = {"date_from": "2026-11-20", "date_to": "2026-11-20"}
    out = tool(client, ai, ASHA, **day)
    assert (out["assignments"], out["distinct_leads"]) == (7, 7)
    assert (out["by_assignee"], out["by_assigner"]) == ({"Sai Kiran": 7}, {"Asha Rao": 7})
    assert (out["from"], out["to"], out["time_zone"]) == ("20 Nov 2026, 12:00 AM IST", "21 Nov 2026, 12:00 AM IST (not included)",
                                                          "IST (Asia/Kolkata, UTC+05:30)")
    assert out["rows"][0]["at"] == "20 Nov 2026, 06:21 PM IST" and out["scope"].startswith("everyone's")
    # "how many did I assign" (the Admin) and "how many were assigned to Sai": the same seven
    assert tool(client, ai, ASHA, assigned_by_me=True, **day)["assignments"] == 7
    assert tool(client, ai, ASHA, assigned_to_name="Sai", **day)["assignments"] == 7
    assert tool(client, ai, ASHA, assigned_by_name="Priya", **day)["assignments"] == 0  # Priya assigned none of them
    # the Assistant itself assigned none (it has no such action)
    assert out["assistant_assigned"] == 0 and "no action that assigns pooled leads" in out["assistant_note"]
    # why the old answer was 0: the only report counted leads CREATED that day (none), and had no assignments
    old = tool(client, ai, ASHA, name="crm_report", **day)
    assert old["leads"]["created_in_period"] == 0 and "assignment_report" in old["assignments"]


def test_every_way_of_assigning_from_the_pool_counts_once_and_transfers_between_owners_dont(client, sai, ai, team):
    ids = pool(client, 5, "Paths")
    # (login_as switches the one test client to that user: sign in right before each call)
    assert login_as(client, PRIYA).post(f"/api/leads/{ids[0]}/assign", json={"to_user_id": RAVI}).status_code == 200
    request = login_as(client, RAVI).post(f"/api/leads/{ids[1]}/transfer-requests", json={"reason": REASON}).json()
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 200
    assert login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": ids[2:4], "to_user_id": RAVI}).json()["assigned"] == 2
    # then the Admin gives one of them to Tara: a transfer between owners (not an assignment from the pool)
    assert login_as(client, ASHA).put(f"/api/leads/{ids[2]}", json={"owner_id": team["tara"]}).status_code == 200
    stamp(ids[:4], datetime(2026, 11, 20, 12, 0))
    out = tool(client, ai, ASHA, date_from="2026-11-20", date_to="2026-11-20")
    assert (out["assignments"], out["distinct_leads"]) == (4, 4)  # each Transfer History row once
    assert out["by_assignee"] == {"Ravi Kumar": 4}  # who got it then, not who owns it now (one is Tara's now)
    assert out["by_assigner"] == {"Asha Rao": 2, "Priya Sharma": 2}
    assert out["via"] == {"Assign (one lead or several selected)": 3, "approved request": 1}
    assert out["transfers_between_owners_not_counted"] == 1
    # the lead still in the pool, and a lead uploaded with an owner (never assigned from the pool), aren't counted
    upload(login_as(client, ASHA), [["Ana", "Owned", "Owned Co", "owned@paths.example", "", "Ravi Kumar"]])
    assert tool(client, ai, ASHA, date_from="2026-11-20", date_to="2026-11-20")["assignments"] == 4


def test_days_are_ist_days_across_midnight_and_new_yorks_daylight_saving_changes(client, sai, ai):
    ids = pool(client, 9, "Clock")
    assert login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": ids, "to_user_id": sai}).json()["assigned"] == 9
    when = {
        ids[0]: datetime(2026, 11, 20, 13, 29),  # 20 Nov 11:59 PM IST
        ids[1]: datetime(2026, 11, 20, 13, 30),  # 21 Nov 12:00 AM IST: the next IST day
        # 1 Nov 2026: New York goes back from EDT (UTC-4) to EST (UTC-5) at 2 AM
        ids[2]: datetime(2026, 10, 31, 14, 15),  # 31 Oct 11:45 PM IST
        ids[3]: datetime(2026, 10, 31, 14, 45),  # 1 Nov 12:15 AM IST
        ids[4]: datetime(2026, 11, 1, 13, 15),   # 1 Nov 11:45 PM IST (EST by then)
        ids[5]: datetime(2026, 11, 1, 13, 45),   # 2 Nov 12:15 AM IST
        # 8 Mar 2026: New York goes forward from EST to EDT at 2 AM
        ids[6]: datetime(2026, 3, 7, 13, 45),    # 8 Mar 12:15 AM IST (EST)
        ids[7]: datetime(2026, 3, 8, 14, 15),    # 8 Mar 11:45 PM IST (EDT by then)
        ids[8]: datetime(2026, 3, 8, 14, 45),    # 9 Mar 12:15 AM IST
    }
    for lead_id, at in when.items():
        stamp([lead_id], at)
    count = lambda day: tool(client, ai, ASHA, date_from=day, date_to=day)["assignments"]  # noqa: E731
    assert [count(d) for d in ("2026-11-20", "2026-11-21")] == [1, 1]
    assert [count(d) for d in ("2026-10-31", "2026-11-01", "2026-11-02")] == [1, 2, 1]
    assert [count(d) for d in ("2026-03-08", "2026-03-09")] == [2, 1]
    out = tool(client, ai, ASHA, date_from="2026-11-01", date_to="2026-11-01")
    assert [r["at"] for r in out["rows"]] == ["01 Nov 2026, 11:45 PM IST", "01 Nov 2026, 12:15 AM IST"]
    # "today" is today in IST, up to now
    now_ist = datetime.now(BUSINESS_TIMEZONE).replace(tzinfo=None)
    stamp([ids[0]], ist_to_server(now_ist - timedelta(minutes=1)))
    stamp([ids[1]], ist_to_server(datetime.combine(now_ist.date(), datetime.min.time()) - timedelta(minutes=1)))  # yesterday
    today = tool(client, ai, ASHA, period="today")
    assert today["assignments"] == 1 and today["to"] == "now" and today["period"] == "today"


def test_each_user_counts_only_the_assignments_they_may_see(client, sai, ai, team):
    to_sai = pool(client, 3, "SaiScope")
    to_ravi = [i for i in pool(client, 5, "RaviScope") if i not in to_sai][:2]
    login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": to_sai, "to_user_id": sai})
    login_as(client, ASHA).post("/api/leads/bulk-assign", json={"lead_ids": to_ravi, "to_user_id": RAVI})
    stamp(to_sai + to_ravi, datetime(2026, 11, 20, 9, 0))
    day = {"date_from": "2026-11-20", "date_to": "2026-11-20"}
    # Ravi (no team access): only what he received or made; Sai's three aren't counted or named for him
    ravi = tool(client, ai, RAVI, **day)
    assert (ravi["assignments"], ravi["by_assignee"]) == (2, {"Ravi Kumar": 2}) and ravi["scope"].startswith("only")
    assert tool(client, ai, RAVI, assigned_to_name="Sai", **day)["assignments"] == 0
    # Priya (Manager, team records) and the Admin: everyone's
    assert tool(client, ai, PRIYA, **day)["assignments"] == tool(client, ai, ASHA, **day)["assignments"] == 5


def test_a_question_the_report_cant_answer_is_an_error_not_zero(client, sai, ai, monkeypatch):
    day = {"date_from": "2026-11-20", "date_to": "2026-11-20"}
    assert "No single user matches" in tool(client, ai, ASHA, assigned_to_name="Nobody Synthetic", **day)["error"]
    assert "Dates must look like" in tool(client, ai, ASHA, date_from="20/11/2026")["error"]

    def broken(*args, **kwargs):
        raise SQLAlchemyError("synthetic failure")
    monkeypatch.setattr(assistant, "assignment_report", broken)
    failed = tool(client, ai, ASHA, **day)
    assert "isn't known" in failed["error"] and "assignments" not in failed
    # and the model is told never to turn a missing answer into 0, and to use this report for assignments
    prompt = ai[1][0][0]["content"]
    assert "Never turn a missing answer into 0" in prompt and "always use assignment_report" in prompt
    assert "assignment_report" in {t["function"]["name"] for t in assistant.tools_for(type("Me", (), {
        "role": "Admin", "can": lambda self, p: True})())}
