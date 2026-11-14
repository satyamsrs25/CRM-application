"""A new lead tells its owner and the owner's active Manager (Reports To). There is no approval step for new leads, so
the wording only says that a lead was created. Email follows each person's settings and goes out only after the
save is committed. Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin). All data is made up;
email is recorded, never sent."""
import csv
import io

import pytest

from app import mailer
from app.database import get_db
from app.main import app
from app.models import Lead, Notification, RolePermission, User
from app.routers import leads as leads_router
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (the scripted stand-in for the AI model)

PRIYA, RAVI, ASHA = 1, 2, 3
APPROVAL_WORDS = ("approv", "pending", "submit")


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append({"to": to, "subject": subject, "body": body}))
    return sent


def db_session():
    return next(app.dependency_overrides[get_db]())


def setup_users(changes):
    """changes: {user_id: {field: value}} (e.g. Ravi reports to Priya, email settings)."""
    with db_session() as db:
        for user_id, fields in changes.items():
            user = db.get(User, user_id)
            for name, value in fields.items():
                setattr(user, name, value)
        db.commit()


def add_user(full_name, email, role, **fields):
    with db_session() as db:
        user = User(full_name=full_name, email=email, role=role, password_hash="x", **fields)
        db.add(user)
        db.commit()
        return user.id


def bell(user_id):
    with db_session() as db:
        return [(n.title, n.message, n.link) for n in db.query(Notification).filter_by(user_id=user_id).order_by(Notification.id)]


def new_lead(client, **extra):
    body = {"first_name": "Ana", "last_name": "Okafor", "company": "Harbor Synthetic", "source": "Website",
            "email": "ana.okafor@harbor-synthetic.example", "phone": "98765 43210", "phone_country": "IN", **extra}
    return client.post("/api/leads", json=body)


def test_owner_and_reporting_manager_are_told_in_plain_words(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    res = new_lead(client)
    assert res.status_code == 201, res.text
    lead = res.json()
    [(title, message, link)] = bell(RAVI)
    assert title == "Lead created" and link == f"/leads/{lead['id']}"
    assert message.startswith("A new lead has been created and assigned to you.")
    for line in ("Lead: Ana Okafor", "Company: Harbor Synthetic", "Source: Website", "Owner: Ravi Kumar",
                 "Next follow-up: Make first contact"):
        assert line in message, line
    [(m_title, m_message, m_link)] = bell(PRIYA)
    assert m_title == "Lead created for your team" and m_link == f"/leads/{lead['id']}"
    assert m_message.startswith("A new lead has been created for your team member.")
    for line in ("Owner: Ravi Kumar", "Lead: Ana Okafor", "Company: Harbor Synthetic", "Created by: Ravi Kumar"):
        assert line in m_message, line
    for text in (message, m_message, title, m_title):
        assert not any(word in text.lower() for word in APPROVAL_WORDS)  # no approval step exists
    # default settings: Ravi's own new lead and Priya's team notice are stage updates (email off by default)
    assert outbox == []
    assert bell(ASHA) == []


def test_email_follows_each_persons_settings(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA, "email_stage_updates": True}, PRIYA: {"email_stage_updates": True}})
    assert new_lead(client).status_code == 201
    assert sorted((m["to"][0], m["subject"]) for m in outbox) == [
        ("priya@crm.test", "[SalesTrack] Lead created for your team"), ("ravi@crm.test", "[SalesTrack] Lead created")]
    manager_mail = next(m for m in outbox if m["to"] == ["priya@crm.test"])
    assert "Ravi Kumar reports to you" in manager_mail["body"] and "you are the owner" not in manager_mail["body"]
    # Priya turns stage emails off: her bell still shows it, no email
    outbox.clear()
    setup_users({PRIYA: {"email_stage_updates": False}})
    assert new_lead(client, email="second@harbor-synthetic.example", last_name="Second").status_code == 201
    assert [m["to"] for m in outbox] == [["ravi@crm.test"]]
    assert len(bell(PRIYA)) == 2


def test_a_lead_created_for_someone_else_is_an_assignment(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    res = new_lead(login_as(client, ASHA), owner_id=RAVI)
    assert res.status_code == 201, res.text
    [(title, message, _)] = bell(RAVI)
    assert title == "Lead assigned to you" and "Created by: Asha Rao" in message
    assert [m["to"] for m in outbox] == [["ravi@crm.test"]]  # Email me: assignments (on by default)
    assert [t for t, _, _ in bell(PRIYA)] == ["Lead created for your team"]
    assert bell(ASHA) == []  # the Admin who created it isn't told about it


def test_a_manager_creating_a_lead_for_their_team_member_isnt_told(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    assert new_lead(login_as(client, PRIYA), owner_id=RAVI).status_code == 201
    assert [t for t, _, _ in bell(RAVI)] == ["Lead assigned to you"]
    assert bell(PRIYA) == []


@pytest.mark.parametrize("manager", [None, "inactive", "not_a_manager"])
def test_no_active_reporting_manager_means_only_the_owner_is_told(client, outbox, manager):
    if manager == "inactive":
        setup_users({RAVI: {"reports_to_id": PRIYA}, PRIYA: {"is_active": False}})
    elif manager == "not_a_manager":
        other = add_user("Tara Synthetic", "tara@crm.test", "Salesperson")
        setup_users({RAVI: {"reports_to_id": other}})
    assert new_lead(client).status_code == 201
    assert [t for t, _, _ in bell(RAVI)] == ["Lead created"]
    with db_session() as db:
        others = db.query(Notification).filter(Notification.user_id != RAVI).count()
    assert others == 0  # no stand-in recipient: not another Manager, not the Admin


def test_owner_and_manager_the_same_person_is_told_once(client, outbox):
    setup_users({PRIYA: {"reports_to_id": PRIYA}})  # not possible from the app; the notices still never double up
    assert new_lead(login_as(client, PRIYA)).status_code == 201
    assert [t for t, _, _ in bell(PRIYA)] == ["Lead created"]


def test_a_manager_who_cant_open_team_records_gets_no_details(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    with db_session() as db:
        db.add(RolePermission(role="Manager", permission="view_team_records", allowed=False))
        db.commit()
    assert new_lead(client).status_code == 201
    [(title, message, link)] = bell(PRIYA)
    assert message == "A new lead has been created for your team member.\nOwner: Ravi Kumar" and link is None


@pytest.mark.parametrize("change, status", [
    ({"email": "taken@harbor-synthetic.example"}, 409),  # the email is already on a lead
    ({"email": "ana@gmail.com", "company_website": "harbor-synthetic.example"}, 400),  # personal mailbox
    ({"phone": ""}, 422),                                 # the New Lead form's phone is required
    ({"last_name": ""}, 422),
])
def test_a_refused_creation_tells_nobody(client, outbox, change, status):
    setup_users({RAVI: {"reports_to_id": PRIYA, "email_stage_updates": True}, PRIYA: {"email_stage_updates": True}})
    assert new_lead(client, email="taken@harbor-synthetic.example", last_name="First").status_code == 201
    outbox.clear()
    before = (bell(RAVI), bell(PRIYA))
    assert new_lead(client, **change).status_code == status
    assert (bell(RAVI), bell(PRIYA)) == before and outbox == []


def test_nothing_is_sent_when_the_save_fails_after_the_notices(client, outbox, monkeypatch):
    """The notices are written in the same transaction: if the save then fails, no bell and no email remain."""
    setup_users({RAVI: {"reports_to_id": PRIYA, "email_stage_updates": True}, PRIYA: {"email_stage_updates": True}})
    real = leads_router.lead_created_notices

    def notices_then_fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Synthetic failure before the commit")

    monkeypatch.setattr(leads_router, "lead_created_notices", notices_then_fail)
    with pytest.raises(RuntimeError):
        new_lead(client)
    with db_session() as db:
        assert db.query(Lead).count() == 0 and db.query(Notification).count() == 0
    assert outbox == []


def test_the_ai_assistant_creates_through_the_same_path(client, outbox, ai):
    """Same notices for the owner and Manager; the New Lead form's required Phone doesn't apply (it stays optional)."""
    script, _ = ai
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    script += [[call("create_lead", first_name="Mohan", last_name="Reddy", company="PwC Synthetic", source="Referral",
                     email="mohan@pwc-synthetic.example")], "Created lead Mohan Reddy."]
    res = client.post("/api/assistant/chat", json={"message": "Create a lead Mohan Reddy at PwC Synthetic"}).json()
    lead = client.get(f"/api/leads/{res['links'][0]['id']}").json()
    assert lead["phone"] is None
    assert [t for t, _, _ in bell(RAVI)] == ["Lead created"]
    [(title, message, _)] = bell(PRIYA)
    assert title == "Lead created for your team" and "Lead: Mohan Reddy" in message


def upload(client, rows, **form):
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Last Name", "Company", "Email", "Phone"], *rows])
    return client.post("/api/leads/import", files={"file": ("team.csv", out.getvalue().encode(), "text/csv")},
                       data={"dry_run": "false", **form})


def test_an_upload_tells_the_manager_once_per_team_member_never_per_row(client, outbox):
    setup_users({RAVI: {"reports_to_id": PRIYA}, PRIYA: {"email_stage_updates": True}})
    rows = [[f"Row{i}", f"Synthetic{i}", "Upload Synthetic Co", f"row{i}@upload-synthetic.example", ""] for i in range(5)]
    res = upload(login_as(client, ASHA), rows, owner_id=str(RAVI))
    assert res.status_code == 200 and res.json()["created"] == 5, res.text  # phones are optional in uploads
    [(title, message, link)] = bell(PRIYA)
    assert title == "Leads created for your team" and link == "/leads"
    assert message.startswith("5 new leads have been created for your team member.")
    assert "Owner: Ravi Kumar" in message and "Uploaded by: Asha Rao (team.csv)" in message
    assert [t for t, _, _ in bell(RAVI)] == ["Leads assigned to you"]  # the owner's summary, as before
    assert [m["to"] for m in outbox if m["to"] == ["priya@crm.test"]] == [["priya@crm.test"]]  # one email, not five
    # a Manager uploading for their own team isn't told about their own upload
    bell_before = bell(PRIYA)
    more = [[f"More{i}", f"Synthetic{i}", "Upload Synthetic Co", f"more{i}@upload-synthetic.example", ""] for i in range(2)]
    assert upload(login_as(client, PRIYA), more, owner_id=str(RAVI)).status_code == 200
    assert bell(PRIYA) == bell_before


def test_transfer_requests_still_need_approval(client, outbox):
    """Unchanged: a request for someone else's lead waits for the owner, their Manager or the Admin."""
    setup_users({RAVI: {"reports_to_id": PRIYA}})
    lead = new_lead(client).json()
    tara = add_user("Tara Synthetic", "tara@crm.test", "Salesperson", reports_to_id=PRIYA)
    res = login_as(client, tara).post(f"/api/leads/{lead['id']}/transfer-requests", json={"reason": "Synthetic: I met them"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["status"] == "Pending"
    assert login_as(client, RAVI).get(f"/api/leads/{lead['id']}").json()["owner_name"] == "Ravi Kumar"  # not moved yet
