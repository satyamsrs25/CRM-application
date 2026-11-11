"""An opportunity moves forward (Change Stage, Mark as Won, with files, Kanban, Assistant) only when the tasks of its
current stage are done. Ticking a task only completes it; date reminders (the close-date reminder) never hold a deal
up; going back and Mark as Lost are not limited; a refusal changes nothing. All data is made up; no AI is called."""
import io
import itertools
import json
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app import assistant, mailer
from app.database import get_db
from app.main import app
from app.models import Notification, OpportunityAttachment, StageHistory, Task
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin (conftest.py)
TASK = {"title": "Synthetic next step", "due_date": "2030-01-15T10:00:00"}
NAMES = itertools.count(1)
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """Nothing is sent; the emails that would go out are counted."""
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: sent.append(a))
    return sent


def db():
    return next(app.dependency_overrides[get_db]())


def new_opportunity(client, owner=RAVI, stage_task="Synthetic kickoff call") -> dict:
    """A lead converted by its owner: the deal starts at Opportunity with the conversion's task open (the stage's
    work) and the system's close-date reminder (a date reminder)."""
    login_as(client, owner)
    n = next(NAMES)
    lead = client.post("/api/leads", json={"first_name": "Test", "last_name": f"Buyer{n}", "company": f"Synthetic Co {n}",
                                           "email": f"buyer{n}@example.test", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "task": {**TASK, "title": stage_task}, "completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 1000,
        "expected_close_date": "2030-06-30", "note": "Synthetic conversion"})
    assert res.status_code == 200, res.text
    return res.json()["opportunity"]


def tasks_of(client, opp_id):
    return {t["title"]: t for t in client.get(f"/api/opportunities/{opp_id}").json()["tasks"]}


def complete_open(client, opp_id):
    """Ticks every open stage task of the deal (the user's explicit Done)."""
    for t in client.get(f"/api/opportunities/{opp_id}").json()["tasks"]:
        if t["status"] == "Open" and not t["is_date_reminder"]:
            assert client.put(f"/api/tasks/{t['id']}/complete").status_code == 200


def snapshot(opp_id):
    """Everything a refused change must leave as it was."""
    with db() as s:
        return {
            "tasks": sorted((t.id, t.status) for t in s.scalars(select(Task).where(Task.opportunity_id == opp_id))),
            "history": s.scalar(select(func.count()).select_from(StageHistory).where(StageHistory.opportunity_id == opp_id)),
            "notifications": s.scalar(select(func.count()).select_from(Notification)),
            "files": s.scalar(select(func.count()).select_from(OpportunityAttachment)),
        }


def move(client, opp_id, stage, **extra):
    body = {"stage": stage, "note": "Synthetic move", "task": TASK, **extra}
    if stage == "Discovery":
        body.setdefault("discovery_needs", "Synthetic needs")
    return client.put(f"/api/opportunities/{opp_id}/stage", json=body)


def won(client, opp_id, **extra):
    return client.post(f"/api/opportunities/{opp_id}/won", json={"note": "Synthetic win", "task": TASK, "final_value": 900,
                                                                  **extra})


# ---------- the rule ----------

def test_forward_move_waits_for_the_stage_task_and_a_refusal_changes_nothing(client, quiet):
    opp = new_opportunity(client)
    before, emails = snapshot(opp["id"]), len(quiet)
    res = move(client, opp["id"], "Discovery")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail.startswith("Finish the Opportunity stage first: this opportunity has 1 open task:")
    assert '"Synthetic kickoff call" (due 15 Jan 2030, you)' in detail
    assert "Mark each one as done in the Activity tab (Upcoming & Overdue)" in detail and "Nothing was changed." in detail
    assert "Close date coming up" not in detail  # the date reminder isn't stage work
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity"
    assert snapshot(opp["id"]) == before and len(quiet) == emails  # no stage, task, history, notification or email
    # done -> the same move is accepted; the close-date reminder stays open and the new task is the next follow-up
    complete_open(client, opp["id"])
    res = move(client, opp["id"], "Discovery")
    assert res.status_code == 200, res.text
    tasks = tasks_of(client, opp["id"])
    assert tasks["Synthetic kickoff call"]["status"] == "Done"  # completed by the user, not auto-closed
    assert tasks["Synthetic next step"]["status"] == "Open"
    reminder = next(t for title, t in tasks.items() if title.startswith("Close date coming up - "))
    assert reminder["status"] == "Open" and reminder["is_date_reminder"] is True


def test_ticking_a_task_only_completes_it(client):
    opp = new_opportunity(client)
    history = snapshot(opp["id"])["history"]
    task = tasks_of(client, opp["id"])["Synthetic kickoff call"]
    done = client.put(f"/api/tasks/{task['id']}/complete")
    assert done.status_code == 200 and done.json()["status"] == "Done"
    detail = client.get(f"/api/opportunities/{opp['id']}").json()
    assert detail["stage"] == "Opportunity" and snapshot(opp["id"])["history"] == history  # no stage change


def test_confirming_skipped_stages_does_not_get_round_open_tasks(client):
    opp = new_opportunity(client)
    before = snapshot(opp["id"])
    res = move(client, opp["id"], "Proposal", completed_stages=["Discovery"], completed_note="Synthetic: done on a call")
    assert res.status_code == 409 and "Finish the Opportunity stage first" in res.json()["detail"]
    assert snapshot(opp["id"]) == before  # no "Confirmed as completed" history either
    res = won(client, opp["id"], completed_stages=["Discovery", "Proposal"], completed_note="Synthetic")
    assert res.status_code == 409 and snapshot(opp["id"]) == before
    complete_open(client, opp["id"])
    res = move(client, opp["id"], "Proposal", completed_stages=["Discovery"], completed_note="Synthetic: done on a call")
    assert res.status_code == 200, res.text
    notes = [h["note"] for h in client.get(f"/api/opportunities/{opp['id']}/history").json()]
    assert "Confirmed as completed: Synthetic: done on a call" in notes


def test_mark_as_won_waits_for_the_proposal_work(client):
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    assert move(client, opp["id"], "Proposal", completed_stages=["Discovery"]).status_code == 200
    before = snapshot(opp["id"])
    res = won(client, opp["id"])
    assert res.status_code == 409
    assert res.json()["detail"].startswith("Finish the Proposal stage first") and "then move it to Won again" in res.json()["detail"]
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Proposal" and snapshot(opp["id"]) == before
    complete_open(client, opp["id"])
    res = won(client, opp["id"])
    assert res.status_code == 200, res.text
    assert res.json()["stage"] == "Won"
    post_sale = [t for t in res.json()["tasks"] if t["status"] == "Open"]
    assert [t["title"] for t in post_sale] == ["Synthetic next step"]  # the post-sale task stays open on the won deal


def test_a_task_added_during_the_stage_is_part_of_its_work(client):
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    added = client.post("/api/tasks", json={"title": "Synthetic: send the security questionnaire",
                                            "due_date": "2030-02-01T09:00:00", "opportunity_id": opp["id"]})
    assert added.status_code == 201
    res = move(client, opp["id"], "Discovery")
    assert res.status_code == 409 and '"Synthetic: send the security questionnaire"' in res.json()["detail"]


def test_going_back_and_lost_are_not_limited(client):
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    assert move(client, opp["id"], "Discovery").status_code == 200  # its new task is open now
    back = move(client, opp["id"], "Opportunity")
    assert back.status_code == 200, back.text
    lost = client.post(f"/api/opportunities/{opp['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic"})
    assert lost.status_code == 200 and lost.json()["stage"] == "Lost"


def test_task_of_someone_else_is_named_and_completed_by_them_or_a_manager(client):
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    # the Manager gives Priya (herself) a task on Ravi's deal
    given = login_as(client, PRIYA).post("/api/tasks", json={"title": "Synthetic: legal review", "owner_id": PRIYA,
                                                               "due_date": "2030-03-01T09:00:00", "opportunity_id": opp["id"]})
    assert given.status_code == 201
    res = move(login_as(client, RAVI), opp["id"], "Discovery")
    assert res.status_code == 409 and '"Synthetic: legal review" (due 01 Mar 2030, Priya Sharma)' in res.json()["detail"]
    assert client.put(f"/api/tasks/{given.json()['id']}/complete").status_code in (403, 404)  # not Ravi's task
    assert login_as(client, PRIYA).put(f"/api/tasks/{given.json()['id']}/complete").status_code == 200
    assert move(login_as(client, RAVI), opp["id"], "Discovery").status_code == 200


def test_people_who_cannot_edit_the_deal_get_403_not_the_task_list(client):
    opp = new_opportunity(client)
    login_as(client, ASHA)
    other = client.post("/api/users", json={"full_name": "Sam Tester", "email": "sam@crm.test", "password": "Password123",
                                            "role": "Salesperson"})
    assert other.status_code == 201
    res = move(login_as(client, other.json()["id"]), opp["id"], "Discovery")
    assert res.status_code in (403, 404) and "Synthetic kickoff call" not in res.text
    res = won(client, opp["id"])
    assert res.status_code in (403, 404) and "Synthetic kickoff call" not in res.text


def test_legacy_system_follow_ups_count_and_only_the_systems_own_date_reminder_is_left_out(client):
    """Deals saved before this change can have the system's old automatic follow-up ("Follow up on proposal - ...")
    open: it is stage work. A task typed by a person never counts as a date reminder, whatever its title."""
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    assert move(client, opp["id"], "Proposal", completed_stages=["Discovery"]).status_code == 200
    complete_open(client, opp["id"])
    with db() as s:
        s.add(Task(title=f"Follow up on proposal - {opp['name']}", due_date=datetime(2030, 1, 5, 9),
                   status="Open", priority="High", is_auto=True, owner_id=RAVI, opportunity_id=opp["id"]))
        s.commit()
    res = won(client, opp["id"])
    assert res.status_code == 409 and f'"Follow up on proposal - {opp["name"]}"' in res.json()["detail"]
    complete_open(client, opp["id"])
    lookalike = client.post("/api/tasks", json={"title": "Close date coming up - typed by a person",
                                                "due_date": "2030-02-01T09:00:00", "opportunity_id": opp["id"]})
    assert lookalike.status_code == 201 and lookalike.json()["is_date_reminder"] is False
    res = won(client, opp["id"])
    assert res.status_code == 409 and "typed by a person" in res.json()["detail"]
    complete_open(client, opp["id"])
    assert won(client, opp["id"]).status_code == 200


def test_long_lists_are_shortened(client):
    opp = new_opportunity(client)
    for i in range(6):
        client.post("/api/tasks", json={"title": f"Synthetic step {i}", "due_date": f"2030-04-0{i + 1}T09:00:00",
                                        "opportunity_id": opp["id"]})
    detail = move(client, opp["id"], "Discovery").json()["detail"]
    assert "this opportunity has 7 open tasks:" in detail and "; and 2 more." in detail


# ---------- the same rule with files (all or nothing) ----------

def test_stage_change_with_files_is_refused_before_any_file_is_saved(client, quiet):
    opp = new_opportunity(client)
    before, emails = snapshot(opp["id"]), len(quiet)
    res = client.post(f"/api/opportunities/{opp['id']}/stage-with-files", data={
        "stage": "Discovery", "note": "Synthetic", "task": json.dumps(TASK), "discovery_needs": "Synthetic needs"},
        files=[("files", ("proposal.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert res.status_code == 409 and "Finish the Opportunity stage first" in res.json()["detail"]
    assert snapshot(opp["id"]) == before and len(quiet) == emails
    complete_open(client, opp["id"])
    res = client.post(f"/api/opportunities/{opp['id']}/stage-with-files", data={
        "stage": "Discovery", "note": "Synthetic", "task": json.dumps(TASK), "discovery_needs": "Synthetic needs"},
        files=[("files", ("proposal.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert res.status_code == 200, res.text
    assert [(f["filename"], f["stage"]) for f in client.get(f"/api/opportunities/{opp['id']}/attachments").json()] == \
        [("proposal.pdf", "Discovery")]


def test_won_with_files_is_refused_before_any_file_is_saved(client):
    opp = new_opportunity(client)
    complete_open(client, opp["id"])
    assert move(client, opp["id"], "Proposal", completed_stages=["Discovery"]).status_code == 200
    before = snapshot(opp["id"])
    res = client.post(f"/api/opportunities/{opp['id']}/won-with-files", data={
        "note": "Synthetic win", "task": json.dumps(TASK), "final_value": "900"},
        files=[("files", ("signed.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert res.status_code == 409 and snapshot(opp["id"]) == before
    complete_open(client, opp["id"])
    res = client.post(f"/api/opportunities/{opp['id']}/won-with-files", data={
        "note": "Synthetic win", "task": json.dumps(TASK), "final_value": "900"},
        files=[("files", ("signed.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert res.status_code == 200 and res.json()["stage"] == "Won"


# ---------- the Assistant uses the same operations (scripted model, no AI service) ----------

def call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_assistant_moves_follow_the_same_rule(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    opp = new_opportunity(client)
    seen = []
    script = [[call("move_opportunity_stage", opportunity_id=opp["id"], stage="Discovery", note="Synthetic",
                    task_title="Synthetic next step", task_due_date="2030-01-15T10:00")],
              "That deal still has an open task."]
    monkeypatch.setattr(assistant, "call_model", lambda messages: seen.append(messages) or (
        {"role": "assistant", "content": step} if isinstance(step := script.pop(0), str)
        else {"role": "assistant", "content": "", "tool_calls": step}))
    res = client.post("/api/assistant/chat", json={"message": "Move the synthetic deal to Discovery"})
    assert res.status_code == 200, res.text
    told = json.loads(seen[1][-1]["content"])["error"]
    assert told.startswith("Finish the Opportunity stage first") and "Synthetic kickoff call" in told
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity"
    # Mark as Won through the Assistant (after the user's Confirm) is refused the same way
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], final_amount=900, note="Synthetic win",
                     completed_stages=["Discovery", "Proposal"], task_title="Synthetic handover",
                     task_due_date="2030-01-20T10:00")]]
    first = client.post("/api/assistant/chat", json={"message": "Mark it won"}).json()
    script += ["It can't be won yet."]
    done = client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": first["pending"],
                                                       "confirmed": True})
    assert done.status_code == 200, done.text
    tool_reply = [m for m in done.json()["messages"] if m.get("role") == "tool"][-1]
    assert "Finish the Opportunity stage first" in json.loads(tool_reply["content"])["error"]
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity"
