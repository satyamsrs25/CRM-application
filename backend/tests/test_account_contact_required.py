"""New Account (issue 3): Account Name and Industry are required; no Phone on the form (optional in the API, kept as
given); Website and Company LinkedIn URL are optional and checked when given.
New Contact (issue 7): First Name, Last Name and Email are required; Phone is optional and checked for its country
(India by default) and saved in international format; the LinkedIn Profile URL is optional (a person's profile).
The rules apply to direct creation (the API and the Assistant's tools) only: lead conversion, imports and older
records keep working. A valid number format doesn't show that the number exists or belongs to the contact.
All data is made up."""
import json

import pytest
from sqlalchemy import func, select

from app import assistant, schemas
from app.database import get_db
from app.main import app
from app.models import Account, Contact
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)
from test_assistant_workspace import chat, tool

PRIYA, RAVI, ASHA = 1, 2, 3
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
ACCOUNT = {"name": "Synthetic Harbor Co", "industry": "Logistics"}
CONTACT = {"first_name": "Ana Maria", "last_name": "Okafor", "email": "ana.okafor@harbor.example"}
BLANKS = [None, "", "   ", "\t\n"]


def db_count(model) -> int:
    with next(app.dependency_overrides[get_db]()) as db:
        return db.scalar(select(func.count()).select_from(model))


def account(client, **changes):
    res = client.post("/api/accounts", json={**ACCOUNT, **changes})
    assert res.status_code == 201, res.text
    return res.json()


def contact(client, **changes):
    body = {**CONTACT, **changes}
    body.setdefault("account_id", account(client)["id"] if "account_id" not in changes else changes["account_id"])
    return client.post("/api/contacts", json=body)


def errors(res) -> dict:
    return {e["loc"][-1]: e["msg"] for e in res.json()["detail"]}


# ---------- New Account ----------

@pytest.mark.parametrize("field, message", [("name", schemas.ACCOUNT_NAME_REQUIRED),
                                            ("industry", schemas.ACCOUNT_INDUSTRY_REQUIRED)])
@pytest.mark.parametrize("value", ["missing", *BLANKS])
def test_an_account_needs_a_name_and_industry(client, field, message, value):
    body = {k: v for k, v in ACCOUNT.items() if not (k == field and value == "missing")}
    if value != "missing":
        body[field] = value
    res = client.post("/api/accounts", json=body)
    assert res.status_code == 422 and errors(res)[field] == message
    assert db_count(Account) == 0  # nothing saved


def test_an_account_saves_without_a_phone(client):
    created = account(client, industry=" Retail ")
    assert (created["phone"], created["industry"], created["website"], created["linkedin_url"]) == (None, "Retail", None, None)
    assert created["owner_id"] == RAVI


def test_website_and_company_linkedin_are_optional_and_checked_when_given(client):
    made = account(client, website="harbor.example", linkedin_url="www.linkedin.com/company/synthetic-harbor")
    assert (made["website"], made["linkedin_url"]) == ("https://harbor.example", "https://www.linkedin.com/company/synthetic-harbor")
    assert account(client, website="", linkedin_url="  ")["website"] is None
    bad_site = client.post("/api/accounts", json={**ACCOUNT, "website": "harbor"})
    assert bad_site.status_code == 422 and errors(bad_site)["website"] == "Enter a valid web address"
    bad_page = client.post("/api/accounts", json={**ACCOUNT, "linkedin_url": "https://harbor.example/about"})
    assert bad_page.status_code == 422 and errors(bad_page)["linkedin_url"] == "Enter a LinkedIn address (linkedin.com/...)"
    assert db_count(Account) == 2


def test_a_phone_sent_through_the_api_is_still_optional_and_kept_as_given(client):
    created = account(client, phone="  +44 (20) 7946-0958 ext. 12 ")
    assert created["phone"] == "+44 (20) 7946-0958 ext. 12"  # no country rule for accounts
    assert client.post("/api/accounts", json={**ACCOUNT, "phone": "1" * 31}).status_code == 422  # length limit kept
    assert client.post("/api/accounts", json={**ACCOUNT, "industry": "x" * 101}).status_code == 422


def test_a_salesperson_still_cant_create_an_account_for_someone_else(client):
    assert client.post("/api/accounts", json={**ACCOUNT, "owner_id": PRIYA}).status_code == 403
    assert db_count(Account) == 0


def test_stored_account_phones_are_kept_and_shown(client):
    with next(app.dependency_overrides[get_db]()) as db:
        old = Account(name="Synthetic Phone Co", industry="Retail", phone="555-0100 ext 5", owner_id=RAVI)
        db.add(old)
        db.commit()
        old_id = old.id
    assert client.get(f"/api/accounts/{old_id}").json()["phone"] == "555-0100 ext 5"
    assert {a["id"]: a["phone"] for a in client.get("/api/accounts").json()}[old_id] == "555-0100 ext 5"


# ---------- New Contact ----------

@pytest.mark.parametrize("field, message", [("first_name", schemas.CONTACT_FIRST_NAME_REQUIRED),
                                            ("last_name", schemas.CONTACT_LAST_NAME_REQUIRED),
                                            ("email", schemas.CONTACT_EMAIL_REQUIRED)])
@pytest.mark.parametrize("value", ["missing", *BLANKS])
def test_a_contact_needs_first_name_last_name_and_email(client, field, message, value):
    body = {**CONTACT, "account_id": account(client)["id"]}
    if value == "missing":
        del body[field]
    else:
        body[field] = value
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 422 and errors(res)[field] == message
    assert db_count(Contact) == 0


@pytest.mark.parametrize("email", ["ana.okafor", "ana@harbor", "@harbor.example", "ana okafor@harbor.example",
                                   "ana@harbor.example, bo@harbor.example", "ana@@harbor.example"])
def test_a_contact_email_must_be_a_valid_address(client, email):
    res = contact(client, email=email)
    assert res.status_code == 422 and errors(res)["email"] == schemas.CONTACT_EMAIL_INVALID
    assert db_count(Contact) == 0


@pytest.mark.parametrize("phone", [None, "", "   "])
def test_a_contact_saves_without_a_phone(client, phone):
    res = contact(client, **({} if phone is None else {"phone": phone}))
    assert res.status_code == 201, res.text
    assert res.json()["phone"] is None


@pytest.mark.parametrize("phone, country, saved", [
    ("98765 43210", None, "+91 98765 43210"),            # India by default
    ("098765-43210", "IN", "+91 98765 43210"),
    ("(98765) 43210", "IN", "+91 98765 43210"),
    ("(212) 555-0142", "US", "+1 212-555-0142"),
    ("(416) 555-0142", "CA", "+1 416-555-0142"),
    ("020 7946 0958", "GB", "+44 20 7946 0958"),
    ("030 901820", "DE", "+49 30 901820"),                # not every country has ten digits
    ("6123 4567", "SG", "+65 6123 4567"),
    ("+44 20 7946 0958", "IN", "+44 20 7946 0958"),       # with +, the number's own code decides
])
def test_a_valid_phone_is_saved_in_international_format(client, phone, country, saved):
    res = contact(client, phone=phone, **({"phone_country": country} if country else {}))
    assert res.status_code == 201, res.text
    assert res.json()["phone"] == saved


@pytest.mark.parametrize("phone, country, message", [
    ("12345", "IN", "Enter a valid phone number for India (+91)."),
    ("98765 4321", "IN", "Enter a valid phone number for India (+91)."),
    ("6123 4567", "IN", "Enter a valid phone number for India (+91)."),
    ("(212) 555-0142", "CA", "Enter a valid phone number for Canada (+1)."),  # a US number isn't a Canadian one
    ("98765 43210 ext. 4", "IN", "Enter a valid phone number for India (+91)."),
    ("call 98765 43210", "IN", "Enter a valid phone number for India (+91)."),
    ("+91 12345", "IN", schemas.PHONE_WITH_CODE_INVALID),
])
def test_an_invalid_phone_is_refused_with_the_country_named(client, phone, country, message):
    res = contact(client, phone=phone, phone_country=country)
    assert res.status_code == 422 and errors(res)["phone"] == message
    assert db_count(Contact) == 0


def test_an_unknown_phone_country_is_refused_not_assumed(client):
    res = contact(client, phone="98765 43210", phone_country="ZZ")
    assert res.status_code == 422 and errors(res)["phone"] == "Choose the phone number's country."
    assert contact(client, phone_country="ZZ").status_code == 422  # the country is checked even without a phone


def test_the_contact_linkedin_profile_is_optional_and_checked(client):
    res = contact(client, linkedin_url="www.linkedin.com/in/Ana-Okafor/")
    assert res.status_code == 201 and res.json()["linkedin_url"] == "https://linkedin.com/in/ana-okafor"
    bad = contact(client, linkedin_url="https://www.linkedin.com/company/harbor")
    assert bad.status_code == 422 and "person's profile address" in errors(bad)["linkedin_url"]
    assert contact(client, linkedin_url="  ").json()["linkedin_url"] is None


def test_no_new_email_uniqueness_or_domain_rule_for_contacts(client):
    acc = account(client)
    for _ in range(2):  # the same address twice, on a domain unlike the account's: both allowed, as before
        assert contact(client, email="shared@other-domain.example", account_id=acc["id"]).status_code == 201
    assert db_count(Contact) == 2


def test_contact_access_and_ownership_rules_are_unchanged(client):
    other = account(login_as(client, PRIYA), name="Synthetic Private Co")
    login_as(client, RAVI)
    assert contact(client, account_id=other["id"]).status_code == 404
    mine = account(client)
    assert contact(client, account_id=mine["id"], owner_id=PRIYA).status_code == 403
    assert contact(client, account_id=999999).status_code == 404
    assert client.post("/api/contacts", json={**CONTACT}).status_code == 422  # the account is still required
    assert contact(client, email="x" * 250 + "@a.example", account_id=mine["id"]).status_code == 422  # length limit kept
    assert db_count(Contact) == 0


@pytest.mark.parametrize("who", [ASHA, PRIYA, RAVI])
def test_every_role_creates_contacts_with_the_same_rules(client, who):
    login_as(client, who)
    acc = account(client)
    assert contact(client, account_id=acc["id"], phone="98765 43210").json()["phone"] == "+91 98765 43210"
    assert contact(client, account_id=acc["id"], first_name=" ").status_code == 422


# ---------- the other ways accounts and contacts are made, and older records ----------

def test_lead_conversion_still_creates_an_account_and_contact_as_before(client):
    lead = client.post("/api/leads", json={"source": "Website", "first_name": "Bo", "last_name": "Lindqvist", "company": "Synthetic Fjord AB",
                                           "email": "bo@fjord.example", "phone": "12345", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert res.status_code == 200, res.text
    assert (res.json()["account"]["industry"], res.json()["account"]["phone"]) == (None, "12345")
    assert res.json()["contact"]["phone"] == "12345"  # the lead's phone, copied as it is (no new rule on conversion)


def test_older_records_with_empty_fields_or_old_phone_formats_still_open_list_and_take_conversions(client):
    with next(app.dependency_overrides[get_db]()) as db:
        legacy = Account(name="Synthetic Legacy Co", owner_id=RAVI)  # created before Industry was required
        db.add(legacy)
        db.flush()
        db.add(Contact(last_name="Legacy", phone="555 0100 x12", account_id=legacy.id, owner_id=RAVI))  # no first name/email
        db.commit()
        legacy_id = legacy.id
    assert client.get(f"/api/accounts/{legacy_id}").status_code == 200
    listed = client.get("/api/contacts", params={"account_id": legacy_id}).json()
    assert [(c["last_name"], c["first_name"], c["email"], c["phone"]) for c in listed] == [("Legacy", None, None, "555 0100 x12")]
    assert client.get(f"/api/contacts/{listed[0]['id']}").json()["phone"] == "555 0100 x12"
    lead = client.post("/api/leads", json={"first_name": "Test", "source": "Website", "last_name": "Iyer", "company": "Synthetic Legacy Co",
                                           "email": "iyer@legacy.example", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
        "account_id": legacy_id})
    assert res.status_code == 200 and res.json()["account"]["id"] == legacy_id
    # a contact can still be added to the older account, with the new rules
    assert contact(client, account_id=legacy_id).status_code == 201


# ---------- the Assistant's tools ----------

def test_the_assistant_tools_mark_the_fields_required():
    defined = {t["function"]["name"]: t["function"]["parameters"] for t in assistant.TOOLS}
    assert set(defined["create_account"]["required"]) == {"name", "industry"}
    assert "linkedin_url" in defined["create_account"]["properties"]
    assert set(defined["create_contact"]["required"]) == {"account_id", "first_name", "last_name", "email"}
    assert {"phone", "phone_country", "linkedin_url"} <= set(defined["create_contact"]["properties"])


def test_the_assistant_cant_create_an_account_or_contact_without_them(client, ai):
    script, seen = ai
    acc = account(client)
    script += [[tool("create_account", {"name": "Synthetic Gap Co", "industry": "  "}),
                call("create_contact", account_id=acc["id"], last_name="Rao", email="not-an-email", phone="12345")],
               "I need a few more details."]
    chat(client, "add Synthetic Gap Co and Dev Rao")
    results = [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]
    assert schemas.ACCOUNT_INDUSTRY_REQUIRED in results[0]["error"]
    assert schemas.CONTACT_FIRST_NAME_REQUIRED in results[1]["error"] and schemas.CONTACT_EMAIL_INVALID in results[1]["error"]
    assert "Enter a valid phone number for India (+91)." in results[1]["error"]
    assert (db_count(Account), db_count(Contact)) == (1, 0)


def test_the_assistant_creates_them_with_the_required_fields(client, ai):
    script, seen = ai
    acc = account(client)
    script += [[tool("create_account", {"name": "Synthetic Gap Co", "industry": "Retail"}),
                call("create_contact", account_id=acc["id"], first_name="Dev", last_name="Rao",
                     email="dev.rao@harbor.example", phone="(212) 555-0151", phone_country="US")],
               "Done."]
    chat(client, "add Synthetic Gap Co (retail) and Dev Rao, dev.rao@harbor.example, (212) 555-0151 in the US")
    results = [json.loads(m["content"]) for m in seen[-1] if m["role"] == "tool"]
    assert "error" not in results[0] and "error" not in results[1]
    assert (db_count(Account), db_count(Contact)) == (2, 1)
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.scalars(select(Contact.phone)).one() == "+1 212-555-0151"
