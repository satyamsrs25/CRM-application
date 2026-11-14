"""No duplicate accounts or contacts: one account per company (the same name, or the same website) and one contact per
email, in every way they are created. All data is made up."""
import io

from sqlalchemy import func, select

from app.database import get_db
from app.main import app
from app.models import Account, Contact
from conftest import login_as
from test_opportunity_duplicates import convert, create, new_lead

PRIYA, RAVI, ASHA = 1, 2, 3
ACCOUNT = {"name": "Brightline Logistics", "industry": "Logistics", "phone": "+1 555 0140",
           "website": "https://www.brightline.example/about"}
CONTACT = {"first_name": "Mira", "last_name": "Shah", "email": "mira@brightline.example", "phone": "+1 212-555-0141"}


def count(model) -> int:
    return next(app.dependency_overrides[get_db]()).scalar(select(func.count()).select_from(model))


def new_account(client, **body):
    return client.post("/api/accounts", json={**ACCOUNT, **body})


def test_one_account_per_company_name_or_website(client):
    login_as(client, PRIYA)
    first = new_account(client)
    assert first.status_code == 201, first.text
    # the same company with "Inc." and other case: the same name
    res = new_account(client, name="BRIGHTLINE LOGISTICS, Inc.", website=None)
    assert res.status_code == 409 and "company name" in res.json()["detail"]
    # another name on the same website (http, no www, another page)
    res = new_account(client, name="Brightline Freight", website="http://brightline.example/contact")
    assert res.status_code == 409 and "website (brightline.example)" in res.json()["detail"]
    assert new_account(client, name="Harbor Freight Labs", website="harbor.example").status_code == 201
    assert count(Account) == 2
    # the form's live check names the existing account, and its owner when the user can't open it
    found = login_as(client, RAVI).get("/api/accounts/duplicates",
                                       params={"name": "Other Co", "website": "www.brightline.example"}).json()
    assert found["matches"] == [{"id": None, "why": "website", "owner": "Priya Sharma", "mine": False,
                                 "name": "Brightline Logistics", "website": ACCOUNT["website"]}]


def test_one_contact_per_email(client):
    login_as(client, PRIYA)
    brightline = new_account(client).json()
    harbor = new_account(client, name="Harbor Freight Labs", website="harbor.example").json()
    assert client.post("/api/contacts", json={**CONTACT, "account_id": brightline["id"]}).status_code == 201
    # the same email on another account (any case), or the same name on the same account: refused
    res = client.post("/api/contacts", json={**CONTACT, "last_name": "Rao", "email": "MIRA@brightline.example",
                                             "account_id": harbor["id"]})
    assert res.status_code == 409 and "already has this email" in res.json()["detail"]
    res = client.post("/api/contacts", json={**CONTACT, "email": "m.shah@brightline.example",
                                             "account_id": brightline["id"]})
    assert res.status_code == 409 and "same name on this account" in res.json()["detail"]
    # the same name on another account is a different person
    assert client.post("/api/contacts", json={**CONTACT, "email": "mira@harbor.example",
                                              "account_id": harbor["id"]}).status_code == 201
    found = client.get("/api/contacts/duplicates", params={"email": "mira@brightline.example"}).json()["matches"]
    assert [(m["why"], m["name"], m["account"]) for m in found] == [("email", "Mira Shah", "Brightline Logistics")]


def test_an_open_leads_email_is_converted_not_added_as_a_contact(client):
    login_as(client, PRIYA)
    account = new_account(client).json()
    new_lead(client, "dev@brightline.example", first="Dev", last="Rao")
    res = client.post("/api/contacts", json={**CONTACT, "first_name": "Dev", "last_name": "Rao",
                                             "email": "dev@brightline.example", "account_id": account["id"]})
    assert res.status_code == 409 and "convert the lead instead" in res.json()["detail"]


def test_converting_a_lead_reuses_the_account_with_the_same_website(client):
    login_as(client, PRIYA)
    account = new_account(client).json()
    lead = new_lead(client, "dev@brightline.example", company="Brightline Group", first="Dev", last="Rao",
                    company_website="brightline.example")
    res = convert(client, lead["id"])
    assert res.status_code in (200, 201), res.text
    assert count(Account) == 1 and res.json()["account"]["id"] == account["id"]


def test_new_opportunity_does_not_copy_a_contact_from_another_account(client):
    login_as(client, PRIYA)
    brightline = new_account(client).json()
    client.post("/api/contacts", json={**CONTACT, "account_id": brightline["id"]})
    res = create(client, name="Harbor rollout", account_name="Harbor Freight Labs", contact_first_name="Mira",
                 contact_last_name="Shah", contact_email="mira@brightline.example")
    assert res.status_code == 409 and "already belongs to the contact Mira Shah" in res.json()["detail"]
    assert count(Contact) == 1 and count(Account) == 1  # nothing half-made


def test_opportunity_upload_finds_the_account_by_name_or_website(client):
    login_as(client, PRIYA)
    new_account(client)
    csv = ("Opportunity Name,Company,Website,Stage,Amount,Contact Email,Contact Last Name\n"
           "Rollout A,\"Brightline Logistics, Inc.\",,Opportunity,1000,a@brightline.example,Ames\n"
           "Rollout B,Brightline Group,https://brightline.example,Opportunity,2000,b@brightline.example,Bose\n")
    res = client.post("/api/opportunities/import", data={"dry_run": "false"},
                      files={"file": ("deals.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 2 and res.json()["accounts_created"] == 0 and count(Account) == 1


def test_an_accounts_page_lists_its_leads(client):
    """Leads converted into the account, and leads from the same company (name or website); only leads you can see."""
    login_as(client, PRIYA)
    account = new_account(client).json()  # Brightline Logistics, brightline.example
    same_name = new_lead(client, "dev@brightline.example", company="Brightline Logistics Inc.", first="Dev", last="Rao")
    same_site = new_lead(client, "ana@brightline.example", company="Brightline Group", first="Ana", last="Bose",
                         company_website="https://www.brightline.example")
    new_lead(client, "om@harbor.example", company="Harbor Freight Labs", first="Om", last="Iyer")  # another company
    converted = new_lead(client, "kai@brightline.example", company="BRIGHTLINE LOGISTICS", first="Kai", last="Sen")
    assert convert(client, converted["id"]).status_code in (200, 201)
    leads = client.get(f"/api/accounts/{account['id']}/leads").json()
    why = {lead["id"]: lead["why"] for lead in leads["items"]}
    assert leads["total"] == 3 and why == {same_name["id"]: "Same company", same_site["id"]: "Same website",
                                           converted["id"]: "Converted"}
    # a Salesperson without team access sees only their own leads on it
    login_as(client, RAVI)
    mine = new_lead(client, "zoe@brightline.example", company="Brightline Logistics", first="Zoe", last="Paul")
    res = client.get(f"/api/accounts/{account['id']}/leads")
    if res.status_code == 200:  # can't open Priya's account at all otherwise (404)
        assert [lead["id"] for lead in res.json()["items"]] == [mine["id"]]
