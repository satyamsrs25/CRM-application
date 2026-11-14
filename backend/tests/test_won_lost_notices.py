"""Opportunity Won, Opportunity Lost and Lead Lost tell the record's owner (not whoever made the change), once, after the
save, with the outcome and a link; email follows the owner's stage-updates setting. There is no Lead Won stage
(converting a lead isn't winning it). Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin). Made-up data;
email is recorded, never sent."""
import json

import pytest

from app import mailer
from app.models import Notification, Opportunity, User
from conftest import finish_stage_tasks, login_as
from test_assistant import ai, call  # noqa: F401 (the scripted stand-in for the AI model)
from test_opportunity_attachments import PDF, db_session, move, new_opportunity, pdf_file

PRIYA, RAVI, ASHA = 1, 2, 3
TASK = {"title": "Synthetic handover", "due_date": "2030-01-20T10:00:00"}
LOST = {"lost_reason": "Price", "lost_notes": "Synthetic: chose a cheaper option"}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject, "body": body}))
    return sent


def stage_emails(on: bool):
    with db_session() as db:
        db.get(User, RAVI).email_stage_updates = on
        db.commit()


def notices(user_id, title):
    with db_session() as db:
        return [(n.message, n.link) for n in db.query(Notification).filter_by(user_id=user_id, title=title)]


def ready_to_win(client):
    opp = new_opportunity(client)  # Ravi's deal
    move(client, opp["id"], "Proposal")
    finish_stage_tasks(client, opp["id"])
    return opp


def won(client, opp_id, **extra):
    return client.post(f"/api/opportunities/{opp_id}/won", json={"task": TASK, "note": "Synthetic: contract signed",
                                                                   "notify_customer": False, **extra})


def test_there_is_no_lead_won_stage(client):
    from app.constants import LEAD_STAGES
    assert "Won" not in LEAD_STAGES


@pytest.mark.parametrize("actor", [RAVI, PRIYA, ASHA])
def test_opportunity_won_tells_the_owner_once(client, outbox, actor):
    opp = ready_to_win(client)
    stage_emails(True)
    outbox.clear()
    res = won(login_as(client, actor), opp["id"], final_value=24000)
    assert res.status_code == 200, res.text
    [(message, link)] = notices(RAVI, "Opportunity won")
    assert link == f"/opportunities/{opp['id']}"
    assert f'"{opp["name"]}" is now at Won' in message and "Final amount: USD 24,000.00" in message
    assert "Note: Synthetic: contract signed" in message
    if actor != RAVI:
        assert notices(actor, "Opportunity won") == []  # the Admin / Manager who did it isn't told
    assert [m["subject"] for m in outbox if m["to"] == ["ravi@crm.test"]] == ["[SalesTrack] Opportunity won"]
    # the same transition again is refused and tells nobody
    assert won(login_as(client, actor), opp["id"]).status_code in (400, 409)
    assert len(notices(RAVI, "Opportunity won")) == 1


def test_the_final_amount_is_in_the_deals_currency(client, outbox):
    opp = ready_to_win(client)
    with db_session() as db:
        db.get(Opportunity, opp["id"]).currency = "INR"
        db.commit()
    assert won(client, opp["id"], final_value=150000).status_code == 200
    [(message, _)] = notices(RAVI, "Opportunity won")
    assert "Final amount: INR 150,000.00" in message and "$" not in message


def test_won_with_files_tells_the_owner_once(client, outbox):
    opp = ready_to_win(client)
    res = login_as(client, ASHA).post(f"/api/opportunities/{opp['id']}/won-with-files",
                                      data={"note": "Synthetic: signed", "task": json.dumps(TASK), "final_value": "1500"},
                                      files=[("files", ("quote.pdf", pdf_file(), PDF))])
    assert res.status_code == 200, res.text
    assert len(notices(RAVI, "Opportunity won")) == 1 and notices(ASHA, "Opportunity won") == []


def test_a_refused_won_tells_nobody(client, outbox):
    opp = new_opportunity(client)
    move(client, opp["id"], "Proposal")
    # an open task of the Proposal stage: Won is refused until it is done (the stage-task gate)
    assert client.post("/api/tasks", json={"title": "Synthetic open proposal work", "due_date": "2030-01-10T10:00:00",
                                           "opportunity_id": opp["id"]}).status_code == 201
    stage_emails(True)
    outbox.clear()
    res = won(login_as(client, ASHA), opp["id"])
    assert res.status_code == 409
    assert notices(RAVI, "Opportunity won") == [] and outbox == []
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Proposal"


@pytest.mark.parametrize("email_on", [True, False])
def test_opportunity_lost_tells_the_owner_with_the_reason(client, outbox, email_on):
    opp = new_opportunity(client)
    stage_emails(email_on)
    outbox.clear()
    res = login_as(client, PRIYA).post(f"/api/opportunities/{opp['id']}/lost", json=LOST)
    assert res.status_code == 200, res.text
    [(message, link)] = notices(RAVI, "Opportunity lost")
    assert "is now at Lost" in message and "Reason: Price" in message and "Notes: Synthetic: chose a cheaper option" in message
    assert link == f"/opportunities/{opp['id']}"
    assert notices(PRIYA, "Opportunity lost") == []
    assert [m["subject"] for m in outbox] == (["[SalesTrack] Opportunity lost"] if email_on else [])
    assert login_as(client, PRIYA).post(f"/api/opportunities/{opp['id']}/lost", json=LOST).status_code in (400, 409)
    assert len(notices(RAVI, "Opportunity lost")) == 1


def test_bulk_lost_tells_each_owner_once_even_with_repeated_ids(client, outbox):
    first, second = new_opportunity(client), new_opportunity(client)
    res = login_as(client, ASHA).post("/api/opportunities/bulk-lost", json={
        "opportunity_ids": [first["id"], second["id"], first["id"]], **LOST})
    assert res.status_code == 200 and res.json()["closed"] == 2, res.text
    assert len(notices(RAVI, "Opportunity lost")) == 2 and notices(ASHA, "Opportunity lost") == []


def test_lead_lost_tells_the_owner(client, outbox):
    lead = client.post("/api/leads", json={"first_name": "Lia", "last_name": "Lostlead", "company": "Lost Synthetic",
                                           "source": "Website", "email": "lia@lost-synthetic.example"}).json()
    stage_emails(True)
    outbox.clear()
    res = login_as(client, ASHA).post(f"/api/leads/{lead['id']}/lost", json=LOST)
    assert res.status_code == 200, res.text
    [(message, link)] = notices(RAVI, "Lead lost")
    assert "Lia Lostlead" in message and "is now at Lost" in message and "Lost at stage: New" in message
    assert "Reason: Price" in message and link == f"/leads/{lead['id']}"
    assert notices(ASHA, "Lead lost") == []
    assert [m["subject"] for m in outbox] == ["[SalesTrack] Lead lost"]
    assert login_as(client, ASHA).post(f"/api/leads/{lead['id']}/lost", json=LOST).status_code in (400, 409)
    assert len(notices(RAVI, "Lead lost")) == 1


def test_converting_a_lead_is_not_a_win(client, outbox):
    opp = new_opportunity(client)  # converted from a lead
    assert opp["stage"] == "Opportunity"
    with db_session() as db:
        titles = {n.title for n in db.query(Notification)}
    assert not {"Opportunity won", "Lead won"} & titles


def test_assistant_won_and_lost_tell_the_owner_once(client, outbox, ai):
    script, _ = ai
    opp = ready_to_win(client)
    lead = client.post("/api/leads", json={"first_name": "Dev", "last_name": "Assistlost", "company": "Assist Synthetic",
                                           "source": "Website", "email": "dev@assist-synthetic.example"}).json()
    script += [[call("mark_opportunity_won", opportunity_id=opp["id"], final_amount=24000, note="Synthetic: signed",
                     task_title="Synthetic handover", task_due_date="2030-01-20T10:00")]]
    first = client.post("/api/assistant/chat", json={"message": "Mark the deal won for 24k"}).json()
    script += ["Done."]
    client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": first["pending"], "confirmed": True})
    script += [[call("mark_lead_lost", lead_id=lead["id"], reason="Price", notes="Synthetic test note")]]
    first = client.post("/api/assistant/chat", json={"message": "Assistlost chose a cheaper option"}).json()
    script += ["Done."]
    client.post("/api/assistant/confirm", json={"messages": first["messages"], "pending": first["pending"], "confirmed": True})
    assert len(notices(RAVI, "Opportunity won")) == 1 and len(notices(RAVI, "Lead lost")) == 1
