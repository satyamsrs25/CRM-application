"""A company (or account) name needs at least one letter or digit, in any language (issue 44): blank, whitespace-only
and punctuation/symbol-only names such as ".." are refused on New Lead, when a lead's company is changed, on New Account
and on New Opportunity's new company. An older lead's unchanged name doesn't block an unrelated edit, and no stored name
is rewritten. Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin). All data is made up."""
import pytest

from app import schemas
from app.database import get_db
from app.main import app
from app.models import Lead
from conftest import login_as

INVALID = "Enter a company name with at least one letter or number."
REQUIRED = "Enter the lead's company."
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}


def lead_body(**changes):
    return {"first_name": "Ana", "last_name": "Okafor", "company": "Harbor Synthetic", "source": "Website",
            "email": "ana@harbor-synthetic.example", **changes}


@pytest.mark.parametrize("name", ["Acme", "3M", "AT&T", "Acme, Inc.", "Société Générale", "株式会社テスト", "Müller GmbH",
                                  "٣ Brothers", "O'Neil & Sons"])
def test_real_company_names_are_fine(name):
    assert schemas.company_name_problem(name) == ""


@pytest.mark.parametrize("name, message", [("", REQUIRED), ("   ", REQUIRED), ("\t", REQUIRED), ("..", INVALID),
                                           (" .. ", INVALID), ("-", INVALID), ("&&", INVALID), ("★", INVALID)])
def test_blank_and_symbol_only_names_are_refused(name, message):
    assert schemas.company_name_problem(name) == message


@pytest.mark.parametrize("company, message", [("..", INVALID), ("   ", REQUIRED), ("!!!", INVALID)])
def test_new_lead_refuses_a_name_without_letters_or_digits(client, company, message):
    res = client.post("/api/leads", json=lead_body(company=company))
    assert res.status_code == 422
    assert any(e["loc"][-1] == "company" and e["msg"].endswith(message) for e in res.json()["detail"]), res.text
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.query(Lead).count() == 0


def test_new_lead_keeps_a_real_name_trimmed(client):
    res = client.post("/api/leads", json=lead_body(company="  Société Générale  "))
    assert res.status_code == 201, res.text
    assert res.json()["company"] == "Société Générale"


def test_an_older_lead_with_a_bad_name_still_saves_unrelated_edits(client):
    with next(app.dependency_overrides[get_db]()) as db:  # an older record (not possible through the form now)
        lead = Lead(first_name="Old", last_name="Name", company="..", source="Website", stage="New", owner_id=2,
                    created_by_id=2, email="old@legacy-synthetic.example")
        db.add(lead)
        db.commit()
        lead_id = lead.id
    # the form sends every field, the company unchanged
    res = client.put(f"/api/leads/{lead_id}", json={"company": "..", "last_name": "Name", "title": "Buyer", "source": "Website"})
    assert res.status_code == 200, res.text
    assert res.json()["company"] == ".." and res.json()["title"] == "Buyer"  # not rewritten
    # changing the company to another bad name is refused; to a real name it saves
    for bad, message in (("--", INVALID), ("   ", REQUIRED)):
        res = client.put(f"/api/leads/{lead_id}", json={"company": bad})
        assert res.status_code == 400 and res.json()["detail"] == message
    assert client.put(f"/api/leads/{lead_id}", json={"company": "Legacy Synthetic Ltd"}).json()["company"] == "Legacy Synthetic Ltd"


def test_new_account_needs_a_letter_or_digit(client):
    res = login_as(client, 3).post("/api/accounts", json={"name": "..", "industry": "Software"})
    assert res.status_code == 422 and "Enter an account name with at least one letter or number." in res.text
    ok = login_as(client, 3).post("/api/accounts", json={"name": "Müller GmbH", "industry": "Software"})
    assert ok.status_code == 201, ok.text


def test_new_opportunitys_new_company_needs_a_letter_or_digit(client):
    res = client.post("/api/opportunities", json={
        "name": "Synthetic pilot", "note": "Synthetic opening note", "task": TASK, "account_name": "..",
        "contact_first_name": "Mia", "contact_last_name": "Lopez", "contact_email": "mia@opp-synthetic.example"})
    assert res.status_code == 422 and INVALID in res.text
