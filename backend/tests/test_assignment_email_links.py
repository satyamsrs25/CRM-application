"""Issue 1: the "View URL" button of a lead assignment email opens that lead.

What the backend owns in that journey: the email is sent only after the assignment is saved (the new owner is in the
database when the email leaves), its button is APP_URL + "/#/leads/<id>" (the address the email recipient opens; no
token or other sign-in data in it), and opening the lead stays subject to the current permissions: the new owner can,
another Salesperson can't (404, the same answer as for a lead that doesn't exist), nor the first owner once the lead
is reassigned. Direct assignment, an approved request and Assign for several selected leads (one summary email).
Users: 1 Priya (Manager: Ravi and Tara report to her), 2 Ravi, 3 Asha (Admin). All data is made up."""
import re

import pytest

from app import mailer
from app.models import Lead
from conftest import login_as
from test_unassigned_pool import ASHA, PRIYA, RAVI, REASON, db, lead_row, pool_rows, pooled_ids, team, upload  # noqa: F401
from app.mailer import title_case

PUBLIC = "https://crm.example.test"  # a synthetic public address of the app


@pytest.fixture
def mails(monkeypatch):
    """Notification emails as they are sent, with every lead's owner read from the database at that moment."""
    monkeypatch.setenv("APP_URL", PUBLIC + "/")  # a trailing / is dropped
    sent = []

    def send(to, subject, body, **kw):
        with db() as s:
            owners = dict(s.query(Lead.id, Lead.owner_id).all())
        sent.append({"to": to, "subject": subject, "body": body, "html": kw.get("html") or "", "owners": owners})

    monkeypatch.setattr(mailer, "send", send)
    return sent


def button(mail):
    """The href of the email's View URL button (the HTML version) and the link in its plain text."""
    [href] = re.findall(r'<a href="([^"]+)"[^>]*>View URL</a>', mail["html"])
    [text] = re.findall(r"View URL: (\S+)", mail["body"])
    return href, text


def to(mails, address, subject="Lead assigned to you"):
    return [m for m in mails if m["to"] == [address] and m["subject"] == title_case(f"[SalesTrack] {subject}")]


def test_a_direct_assignment_email_opens_the_lead_for_its_new_owner_only(client, team, mails):
    upload(login_as(client, ASHA), pool_rows(1))
    [lead_id] = pooled_ids(client)
    res = login_as(client, PRIYA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI})
    assert res.status_code == 200, res.text
    [mail] = to(mails, "ravi@crm.test")
    assert mail["owners"][lead_id] == RAVI  # sent after the save: the lead was already Ravi's
    href, text = button(mail)
    assert href == text == f"{PUBLIC}/#/leads/{lead_id}"  # the app's address, the lead's page, nothing else
    # opening it follows today's permissions: Ravi can, another team's Salesperson can't (as if it didn't exist)
    assert login_as(client, RAVI).get(f"/api/leads/{lead_id}").json()["owner_id"] == RAVI
    other = login_as(client, team["sam"]).get(f"/api/leads/{lead_id}")
    assert other.status_code == 404 and other.json()["detail"] == "This lead doesn't exist or you don't have access to it"


def test_an_approved_request_email_opens_the_lead(client, team, mails):
    upload(login_as(client, ASHA), pool_rows(1))
    [lead_id] = pooled_ids(client)
    request = login_as(client, RAVI).post(f"/api/leads/{lead_id}/transfer-requests", json={"reason": REASON}).json()
    assert login_as(client, PRIYA).post(f"/api/transfer-requests/{request['id']}/approve", json={}).status_code == 200
    [mail] = to(mails, "ravi@crm.test")
    assert mail["owners"][lead_id] == RAVI
    assert button(mail) == (f"{PUBLIC}/#/leads/{lead_id}",) * 2
    assert "approved your request" in mail["body"]


def test_assign_for_selected_leads_sends_one_summary_that_opens_the_lead_or_the_list(client, team, mails):
    upload(login_as(client, ASHA), pool_rows(3))
    one, *two = pooled_ids(client)
    admin = login_as(client, ASHA)
    assert admin.post("/api/leads/bulk-assign", json={"lead_ids": two, "to_user_id": RAVI}).json()["assigned"] == 2
    [summary] = to(mails, "ravi@crm.test", "Leads assigned to you")
    assert all(summary["owners"][i] == RAVI for i in two)
    assert button(summary) == (f"{PUBLIC}/#/leads",) * 2  # several leads: the Leads list
    assert admin.post("/api/leads/bulk-assign", json={"lead_ids": [one], "to_user_id": RAVI}).json()["assigned"] == 1
    [single] = to(mails, "ravi@crm.test")
    assert single["owners"][one] == RAVI
    assert button(single) == (f"{PUBLIC}/#/leads/{one}",) * 2  # one lead: that lead


def test_a_reassigned_lead_refuses_the_old_email_link_and_a_refused_assignment_sends_nothing(client, team, mails):
    upload(login_as(client, ASHA), pool_rows(1))
    [lead_id] = pooled_ids(client)
    login_as(client, PRIYA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI})
    [first] = to(mails, "ravi@crm.test")
    # the Admin gives it to Tara afterwards: Ravi's email link now meets today's permissions
    assert login_as(client, ASHA).put(f"/api/leads/{lead_id}", json={"owner_id": team["tara"]}).status_code == 200
    assert button(first)[0] == f"{PUBLIC}/#/leads/{lead_id}"
    assert login_as(client, RAVI).get(f"/api/leads/{lead_id}").status_code == 404
    assert login_as(client, team["tara"]).get(f"/api/leads/{lead_id}").status_code == 200
    # assigning a lead that already has an owner is refused (409) and emails nobody
    before = len(mails)
    assert login_as(client, PRIYA).post(f"/api/leads/{lead_id}/assign", json={"to_user_id": RAVI}).status_code == 409
    assert len(mails) == before and lead_row(lead_id).owner_id == team["tara"]
