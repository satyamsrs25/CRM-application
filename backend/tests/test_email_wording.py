"""Automatic emails: a "View URL" button (not "Open in SalesTrack"), title-case subjects, people's names with
standard capitals and lines that start with a capital. Users: 1 Priya (Manager), 2 Ravi (Salesperson),
3 Asha (Admin). All data is made up."""
from app import mailer
from app.database import get_db
from app.main import app
from app.models import User
from app.services import notify
from conftest import login_as


def db():
    return next(app.dependency_overrides[get_db]())


def test_title_case_subjects():
    cases = {
        "[SalesTrack] Lead assigned to you": "[SalesTrack] Lead Assigned to You",
        "[SalesTrack] Your account is ready": "[SalesTrack] Your Account Is Ready",
        "[SalesTrack] Lead requested from the Unassigned Pool": "[SalesTrack] Lead Requested From the Unassigned Pool",
        "[SalesTrack] Your team's data was downloaded": "[SalesTrack] Your Team's Data Was Downloaded",
        "[SalesTrack] No activity for 3+ days": "[SalesTrack] No Activity for 3+ Days",
        "[SalesTrack] Leads to go through": "[SalesTrack] Leads to Go Through",
        "[SalesTrack] Deal with IBM via iPhone app": "[SalesTrack] Deal With IBM via iPhone App",
        "[SalesTrack] what to look for": "[SalesTrack] What to Look For",  # first and last word always capitalized
    }
    for text, expected in cases.items():
        assert mailer.title_case(text) == expected


def test_people_names_and_lines_get_standard_capitals():
    assert mailer.person_name("vikram sake") == "Vikram Sake"
    assert mailer.person_name("SADANAND YERULE") == "Sadanand Yerule"
    assert mailer.person_name("anne-marie o'brien") == "Anne-Marie O'Brien"
    assert mailer.person_name("Ian McKay RK") == "Ian McKay RK"  # mixed case and initials stay as typed
    assert mailer.person_name("") == ""
    text = "\n".join(["no open tasks: add the next follow-up.", "Lead: maria lopez", "assigned by: vikram sake",
                      "Company: ACME LTD", "Email: maria.lopez@acme.example", "maria.lopez@acme.example wrote"])
    assert mailer.tidy_text(text).split("\n") == [
        "No open tasks: add the next follow-up.", "Lead: Maria Lopez", "Assigned by: Vikram Sake",
        "Company: ACME LTD", "Email: maria.lopez@acme.example", "maria.lopez@acme.example wrote"]


def test_a_notification_email_has_a_view_url_button_and_standard_capitals(client, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append((subject, body, kw.get("html"))))
    with db() as s:
        s.get(User, 2).full_name = "ravi kumar"
        notify(s, 2, "Lead assigned to you", "vikram sake assigned you a lead.\nLead: maria lopez", link="/leads/7",
               category="assignment")
        s.commit()
    subject, body, html = sent[-1]
    assert subject == "[SalesTrack] Lead Assigned to You"
    assert body.startswith("Hi Ravi,\n\nVikram sake assigned you a lead.\nLead: Maria Lopez\n\nView URL: ")
    assert body.split("\n")[5].endswith("/#/leads/7")
    assert ">View URL</a>" in html and "Open in SalesTrack" not in html and "Hi Ravi," in html
    with db() as s:  # the bell keeps the text as it was written
        bell = login_as(client, 2).get("/api/notifications").json()
        assert bell[0]["title"] == "Lead assigned to you" and bell[0]["message"].startswith("vikram sake")


def test_the_welcome_email_for_a_new_user_has_a_view_url_button(client, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: sent.append((to, subject, body, kw.get("html"))))
    login_as(client, 3)
    res = client.post("/api/users", json={"full_name": "neha iyer", "email": "neha.iyer@company.com",
                                          "role": "Salesperson", "password": "Synthetic@2026"})
    assert res.status_code in (200, 201), res.text
    to, subject, body, html = next(m for m in sent if m[0] == ["neha.iyer@company.com"])
    assert subject == "[SalesTrack] Your Account Is Ready"
    assert body.startswith("Hi Neha Iyer,\n\nAn account was created for you in SalesTrack CRM as Salesperson.\n\nView URL: ")
    assert "Username: neha.iyer@company.com" in body and "Temporary password: Synthetic@2026" in body
    assert ">View URL</a>" in html and "Hi Neha Iyer," in html
