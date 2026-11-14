"""Issue 7 (New Contact) and issue 2 (New Opportunity > New contact): the contact LinkedIn lookup and the new
contact's rules. Apollo is never called: every lookup goes to the mocked transport of test_lead_enrichment, and any
other Apollo call fails the test. Nothing is sent. All people and companies are made up."""
import httpx
import pytest
from sqlalchemy import func, select

from app import apollo, schemas
from app.database import get_db
from app.main import app
from app.models import Account, Contact, Opportunity, StageHistory, Task
from conftest import login_as
from test_lead_enrichment import JANE, apollo_api, isolated, person  # noqa: F401 (fixtures: mocked Apollo, no key)

PRIYA, RAVI, ASHA = 1, 2, 3
ENDPOINT = "/api/contacts/enrichment"
TASK = {"title": "Synthetic first task", "due_date": "2030-01-15T10:00:00"}
NEW_CONTACT = {"contact_first_name": "Ana", "contact_last_name": "Okafor", "contact_email": "ana.okafor@harbor.example"}
WORK_PHONE = [{"type_cd": "work_direct", "raw_number": "+1 212-555-0142"}]


def counts() -> dict:
    with next(app.dependency_overrides[get_db]()) as db:
        return {m.__name__: db.scalar(select(func.count()).select_from(m))
                for m in (Account, Contact, Opportunity, StageHistory, Task)}


def look_up(client, company=None, url=JANE):
    return client.post(ENDPOINT, json={"linkedin_url": url, "company": company})


def account(client, name="Synthetic Co", **extra):
    res = client.post("/api/accounts", json={"name": name, "industry": "Logistics", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def new_opportunity(client, **body):
    return client.post("/api/opportunities", json={"name": "Synthetic pilot", "note": "Synthetic opening note", "task": TASK,
                                                   **body})


# ---------- the contact LinkedIn lookup ----------

def test_a_matched_profile_fills_only_the_persons_details(client, apollo_api):
    seen, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=WORK_PHONE)}))
    before = counts()
    res = look_up(client, company="Synthetic Co, Inc.")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "matched" and body["url_verified"] is True
    assert body["fields"] == {"first_name": "Jane", "last_name": "Doe", "job_title": "Head of Operations",
                              "email": "jane.doe@synthetic-co.example", "phone": "+1 212-555-0142"}
    assert not set(body["fields"]) & {"company", "industry", "company_website", "company_linkedin_url"}  # never the account
    assert (body["employer"], body["employer_matches"]) == ("Synthetic Co", True)  # "Inc." etc. are ignored
    assert counts() == before  # a lookup saves nothing
    assert len(seen) == 1


def test_another_employer_is_reported_and_nothing_about_the_account_changes(client, apollo_api):
    mine = account(client, name="Harbor Logistics")
    before = counts()
    body = look_up(client, company="Harbor Logistics").json()
    assert body["status"] == "matched" and body["fields"]["first_name"] == "Jane"
    assert (body["employer"], body["employer_matches"]) == ("Synthetic Co", False)
    assert counts() == before
    assert client.get(f"/api/accounts/{mine['id']}").json()["name"] == "Harbor Logistics"


def test_no_account_chosen_yet_is_not_a_mismatch(client, apollo_api):
    body = look_up(client).json()
    assert (body["employer"], body["employer_matches"]) == ("Synthetic Co", None)


def test_choosing_another_account_rechecks_without_a_new_apollo_request(client, apollo_api):
    seen, _ = apollo_api
    assert look_up(client, company="Synthetic Co").json()["employer_matches"] is True
    again = look_up(client, company="Harbor Logistics").json()
    assert again["employer_matches"] is False and again["cached"] is True
    assert len(seen) == 1  # the same profile: Apollo's answer is reused (no new credit)


def test_a_missing_or_unverified_email_is_left_out_and_explained(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(email_status="guessed")}))
    body = look_up(client).json()
    assert body["status"] == "matched" and "email" not in body["fields"]
    assert "unverified" in body["unavailable"]["email"]
    assert "phone" in body["unavailable"]  # no direct business number: never invented


@pytest.mark.parametrize("reply, status", [
    (httpx.Response(200, json={"person": None}), "no_match"),
    (httpx.Response(200, json={"person": person(match_confidence="low")}), "no_match"),
    (httpx.Response(200, json={"person": person(linkedin_url="http://www.linkedin.com/in/someone-else")}), "unverified"),
])
def test_an_unmatched_or_unverified_profile_fills_nothing(client, apollo_api, reply, status):
    _, replies = apollo_api
    replies.append(reply)
    body = look_up(client, company="Synthetic Co").json()
    assert body["status"] == status and body["fields"] == {} and body["employer"] is None
    assert body["employer_matches"] is None


def test_a_failed_lookup_is_an_error_and_manual_creation_still_works(client, apollo_api):
    _, replies = apollo_api
    replies.append(httpx.Response(500, json={"error": "PRIVATE_PROVIDER_DETAIL"}))
    res = look_up(client, company="Synthetic Co")
    assert res.status_code >= 400 and "PRIVATE_PROVIDER_DETAIL" not in res.text
    acc = account(client)
    made = client.post("/api/contacts", json={"first_name": "Ana", "last_name": "Okafor", "email": "ana@harbor.example",
                                              "account_id": acc["id"]})
    assert made.status_code == 201


def test_an_invalid_address_is_refused_before_any_lookup(client, apollo_api):
    seen, _ = apollo_api
    for url in ("https://www.linkedin.com/company/harbor", "lnkd.in/abc", "https://evil-linkedin.com/in/jane"):
        assert look_up(client, url=url).status_code == 422
    assert seen == []


def test_the_lookup_is_off_without_an_apollo_key(client):
    res = look_up(client)
    assert res.status_code == 503  # the form says autofill isn't available; nothing is called


@pytest.mark.parametrize("who", [ASHA, PRIYA, RAVI])
def test_every_role_that_adds_contacts_can_look_one_up(client, apollo_api, who):
    assert look_up(login_as(client, who), company="Synthetic Co").status_code == 200
    # the lead lookup (New Lead) is unchanged
    assert client.post("/api/leads/enrichment", json={"linkedin_url": JANE}).json()["fields"]["company"] == "Synthetic Co"



@pytest.mark.parametrize("number", ["uiadcna", "555-0142", "(212) 555-0142", "+1 555", "+91 12345", "+1 212-555-0142 ext. 9"])
def test_a_malformed_or_countryless_phone_from_apollo_never_reaches_the_form(client, apollo_api, number):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=[{"type_cd": "work_direct", "raw_number": number}])}))
    body = look_up(client, company="Synthetic Co").json()
    assert body["status"] == "matched" and "phone" not in body["fields"]
    assert "isn't a valid phone number with its country code" in body["unavailable"]["phone"]
    assert body["fields"]["first_name"] == "Jane"  # the rest is still filled


@pytest.mark.parametrize("number, saved", [("+1 212-555-0142", "+1 212-555-0142"), ("+12125550142", "+1 212-555-0142"),
                                           ("+91 98765 43210", "+91 98765 43210")])
def test_a_valid_international_phone_from_apollo_is_used(client, apollo_api, number, saved):
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=[{"type_cd": "work_direct", "raw_number": number}])}))
    assert look_up(client).json()["fields"]["phone"] == saved


def test_the_lead_lookup_follows_the_same_phone_rule(client, apollo_api):
    """New Lead needs a valid phone (Manimohan issue 35): a number without its country code is left blank, with the
    reason, for the user to enter (it used to be filled as written)."""
    _, replies = apollo_api
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=[{"type_cd": "work_direct", "raw_number": "(212) 555-0142"}])}))
    body = client.post("/api/leads/enrichment", json={"linkedin_url": JANE}).json()
    assert "phone" not in body["fields"]
    assert "isn't a valid phone number with its country code" in body["unavailable"]["phone"]


# ---------- New Opportunity > New contact ----------

@pytest.mark.parametrize("field, message", [("contact_first_name", schemas.CONTACT_FIRST_NAME_REQUIRED),
                                            ("contact_last_name", schemas.CONTACT_LAST_NAME_REQUIRED),
                                            ("contact_email", schemas.CONTACT_EMAIL_REQUIRED)])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_new_contact_needs_first_name_last_name_and_email(client, field, message, value):
    acc = account(client)
    before = counts()
    res = new_opportunity(client, account_id=acc["id"], **{**NEW_CONTACT, field: value})
    assert res.status_code == 422 and message in res.text
    assert counts() == before  # no account, contact, opportunity, history or task


@pytest.mark.parametrize("extra, message", [
    ({"contact_email": "ana@harbor"}, schemas.CONTACT_EMAIL_INVALID),
    ({"contact_phone": "12345"}, "Enter a valid phone number for India (+91)."),
    ({"contact_phone": "(212) 555-0142", "contact_phone_country": "CA"}, "Enter a valid phone number for Canada (+1)."),
    ({"contact_linkedin_url": "https://www.linkedin.com/company/harbor"}, "person's profile address"),
])
def test_a_new_contacts_email_phone_and_linkedin_are_checked(client, extra, message):
    before = counts()
    res = new_opportunity(client, account_name="Synthetic Delta Ltd", **{**NEW_CONTACT, **extra})
    assert res.status_code == 422 and message in res.text
    assert counts() == before


def test_a_new_contact_is_saved_with_its_phone_and_profile_and_the_chosen_account(client):
    acc = account(client, name="Harbor Logistics")
    res = new_opportunity(client, account_id=acc["id"], **NEW_CONTACT, contact_phone="98765 43210",
                          contact_linkedin_url="linkedin.com/in/Ana-Okafor", contact_title="Buyer")
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["account"]["id"] == acc["id"] and out["account"]["name"] == "Harbor Logistics"  # unchanged
    contact = out["contact"]
    assert (contact["first_name"], contact["last_name"], contact["email"], contact["phone"], contact["linkedin_url"],
            contact["job_title"]) == ("Ana", "Okafor", "ana.okafor@harbor.example", "+91 98765 43210",
                                      "https://linkedin.com/in/ana-okafor", "Buyer")
    blank = new_opportunity(client, name="Second pilot", account_name="Synthetic Echo", **{**NEW_CONTACT,
                            "contact_email": "ana2@echo.example"}, contact_phone="  ")
    assert blank.status_code == 201 and blank.json()["contact"]["phone"] is None  # blank Phone saves


def test_a_new_company_and_new_contact(client):
    res = new_opportunity(client, account_name="Synthetic Delta Ltd", **NEW_CONTACT)
    assert res.status_code == 201, res.text
    assert res.json()["account"]["name"] == "Synthetic Delta Ltd" and res.json()["reused"] == {"account": False, "contact": False}


def test_an_existing_contact_is_reused_without_new_contact_fields(client):
    acc = account(client)
    first = new_opportunity(client, account_id=acc["id"], **NEW_CONTACT, contact_phone="98765 43210").json()["contact"]
    before = counts()
    res = new_opportunity(client, name="Another pilot", account_id=acc["id"], primary_contact_id=first["id"],
                          contact_phone="not checked", contact_email="ignored")
    assert res.status_code == 201, res.text
    assert res.json()["contact"]["id"] == first["id"] and res.json()["reused"]["contact"] is True
    assert res.json()["contact"]["phone"] == "+91 98765 43210"  # untouched
    assert counts()["Contact"] == before["Contact"]


def test_the_same_person_by_email_is_reused_and_duplicates_are_refused(client):
    acc = account(client)
    first = new_opportunity(client, account_id=acc["id"], **NEW_CONTACT).json()
    again = new_opportunity(client, name="Another pilot", account_id=acc["id"], **{**NEW_CONTACT, "contact_first_name": "Ana Maria"})
    assert again.status_code == 201 and again.json()["contact"]["id"] == first["contact"]["id"]  # the same email: reused
    before = counts()
    duplicate = new_opportunity(client, account_id=acc["id"], **NEW_CONTACT)  # the same open deal for the same person
    assert duplicate.status_code == 409
    assert counts() == before


def test_the_comment_task_and_owner_rules_are_unchanged(client):
    base = {"name": "Synthetic pilot", "account_name": "Synthetic Delta Ltd", **NEW_CONTACT}
    assert client.post("/api/opportunities", json={**base, "task": TASK}).status_code == 422  # no comment
    assert client.post("/api/opportunities", json={**base, "note": "Opening"}).status_code == 422  # no task
    assert new_opportunity(client, account_name="Synthetic Delta Ltd", **NEW_CONTACT, owner_id=PRIYA).status_code == 403
    made = new_opportunity(login_as(client, PRIYA), account_name="Synthetic Delta Ltd", **NEW_CONTACT, owner_id=RAVI)
    assert made.status_code == 201 and made.json()["opportunity"]["owner_id"] == RAVI


@pytest.mark.parametrize("who", [ASHA, PRIYA, RAVI])
def test_every_role_creates_an_opportunity_with_a_new_contact(client, who):
    res = new_opportunity(login_as(client, who), account_name=f"Synthetic Role Co {who}", **NEW_CONTACT,
                          contact_phone="(212) 555-0142", contact_phone_country="US")
    assert res.status_code == 201, res.text
    assert res.json()["contact"]["phone"] == "+1 212-555-0142"


def test_the_opportunity_import_still_takes_contacts_without_first_name_or_email(client):
    import csv
    import io

    out = io.StringIO()
    csv.writer(out).writerows([["Opportunity Name", "Company", "Contact Name", "Stage", "Amount"],
                               ["Synthetic import deal", "Synthetic Import Co", "Moreau", "Opportunity", "100"]])
    res = client.post("/api/opportunities/import", files={"file": ("deals.csv", out.getvalue().encode(), "text/csv")},
                      data={"dry_run": "false"})
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1  # the import keeps its own rules


def test_the_assistant_asks_for_the_new_contacts_required_fields():
    from app.assistant import missing_required
    assert missing_required("create_opportunity", {"name": "X", "account_name": "Y", "contact_last_name": "Z"}) == [
        "Contact First Name", "Contact Email"]
    assert missing_required("create_opportunity", {"name": "X", "account_id": 4, "contact_id": 9}) == []


def test_a_countryless_raw_number_uses_apollos_international_form_of_the_same_line(client, apollo_api):
    """Apollo often writes the raw number without the country code; its sanitized form (+...) of the same direct line
    fills the contact's Phone, and New Lead's (both need a valid number with its country)."""
    _, replies = apollo_api
    number = [{"type_cd": "work_direct", "raw_number": "(212) 555-0142", "sanitized_number": "+12125550142"}]
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=number)}))
    body = look_up(client, company="Synthetic Co").json()
    assert body["fields"]["phone"] == "+1 212-555-0142" and "phone" not in body["unavailable"]
    assert "phone_international" not in body
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=number)}))
    from app import apollo
    apollo.reset()  # a new lookup for the lead form (the answer above is kept for 10 minutes)
    lead = client.post("/api/leads/enrichment", json={"linkedin_url": JANE}).json()
    assert lead["fields"]["phone"] == "+1 212-555-0142" and "phone_international" not in lead


def test_a_mobile_number_is_never_used_for_a_contact_either(client, apollo_api):
    _, replies = apollo_api
    number = [{"type_cd": "mobile", "raw_number": "+1 212-555-0199", "sanitized_number": "+12125550199"}]
    replies.append(httpx.Response(200, json={"person": person(phone_numbers=number)}))
    body = look_up(client, company="Synthetic Co").json()
    assert "phone" not in body["fields"] and "555-0199" not in str(body)
