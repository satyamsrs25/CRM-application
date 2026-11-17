"""Field characters (names, company, title...), the same phone number on several records, similar company names
(TCS / Tata Consultancy Services), campaign Cc and a one-person campaign. All data is made up.
Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin)."""
import pytest

from app import campaigns, schemas
from app.database import get_db
from app.main import app
from app.models import Account, Campaign, Lead
from app.opportunity_matches import similar_names
from app.text_rules import company_characters_problem, person_name_problem, text_problem
from conftest import login_as
from test_opportunity_duplicates import convert

PRIYA, RAVI, ASHA = 1, 2, 3


def database():
    return next(app.dependency_overrides[get_db]())


def lead_body(**changes):
    return {"first_name": "Ana", "last_name": "Okafor", "company": "Harbor Synthetic", "source": "Website",
            "email": f"{changes.pop('mailbox', 'ana')}@harbor-synthetic.example", "phone": "+91 98111 22334", **changes}


# ---------- characters ----------

@pytest.mark.parametrize("name", ["Ana", "Anne-Marie", "O'Neil", "D’Souza", "J. R.", "José", "प्रिया", "Nguyễn Văn"])
def test_real_person_names_are_fine(name):
    assert person_name_problem(name, "first name") == ""


@pytest.mark.parametrize("name", ["...", "Buyer1", "Ana!", "<b>Ana</b>", "@@", "Ana_Rao", "🙂"])
def test_person_names_need_letters_only(name):
    assert person_name_problem(name, "last name").startswith("Enter a valid last name")


@pytest.mark.parametrize("name", ["AT&T", "Acme, Inc.", "Yahoo!", "E*Trade", "1-800-Flowers", "(Old) Acme", "3M",
                                  "Société Générale", "株式会社テスト", "@Home Network"])
def test_real_company_names_are_fine(name):
    assert company_characters_problem(name) == "" and schemas.company_name_problem(name) == ""


@pytest.mark.parametrize("name, start", [("Acme ★", "The company name can't contain ★"),
                                         ("Acme <script>", "The company name can't contain < >"),
                                         ("Acme $$$", "The company name can't contain $"),
                                         ("-Acme", "Start the company name"), ("...Acme", "Start the company name")])
def test_company_names_with_other_characters_are_refused(name, start):
    assert schemas.company_name_problem(name).startswith(start)


def test_text_fields():
    assert text_problem("VP, Sales & Marketing (APAC)", "title") == ""
    assert text_problem("Bengaluru, KA 560001", "location", letter=False) == ""
    assert text_problem("<b>CEO</b>", "title").startswith("The title can't contain")
    assert text_problem("1234", "title") == "Enter a title with at least one letter."
    assert text_problem("...", "location", letter=False) == "Enter a location with at least one letter or number."
    assert text_problem("Line 1\nLine 2", "address", letter=False, multiline=True) == ""


def test_new_lead_checks_every_field(client):
    for field, value, message in (("company", "...", "Enter a company name with at least one letter or number."),
                                  ("company", "Acme ★", "can't contain ★"), ("last_name", "Buyer1", "valid last name"),
                                  ("first_name", "@@", "valid first name"), ("title", "<CEO>", "title can't contain"),
                                  ("industry", "1234", "industry with at least one letter"),
                                  ("location", "{x}", "location can't contain")):
        res = client.post("/api/leads", json=lead_body(**{field: value}))
        assert res.status_code == 422 and message in res.text, (field, res.text)
    assert client.post("/api/leads", json=lead_body(first_name="Anne-Marie", last_name="O'Neil")).status_code == 201


def test_an_edit_checks_only_the_fields_it_changes(client):
    db = database()
    old = Lead(first_name="Old", last_name="Buyer1", company="..", title="<CEO>", source="Website", stage="New",
               owner_id=RAVI, created_by_id=RAVI, email="old@legacy-synthetic.example")
    db.add(old)
    db.commit()
    # the form sends every field, unchanged: still saves
    res = client.put(f"/api/leads/{old.id}", json={"first_name": "Old", "last_name": "Buyer1", "company": "..",
                                                   "title": "<CEO>", "industry": "Logistics", "source": "Website"})
    assert res.status_code == 200, res.text
    assert client.put(f"/api/leads/{old.id}", json={"last_name": "Buyer2"}).status_code == 400
    assert client.put(f"/api/leads/{old.id}", json={"title": "<VP>"}).status_code == 400
    assert client.put(f"/api/leads/{old.id}", json={"last_name": "Rao", "title": "VP Sales"}).status_code == 200


def test_new_account_and_contact_check_their_fields(client):
    login_as(client, ASHA)
    res = client.post("/api/accounts", json={"name": "Acme ★", "industry": "Software"})
    assert res.status_code == 422 and "account name can't contain" in res.text
    res = client.post("/api/accounts", json={"name": "Acme", "industry": "<Software>"})
    assert res.status_code == 422 and "industry can't contain" in res.text
    account = client.post("/api/accounts", json={"name": "Acme", "industry": "Software"}).json()
    res = client.post("/api/contacts", json={"first_name": "Mia1", "last_name": "Lopez", "email": "mia@acme.example",
                                             "account_id": account["id"]})
    assert res.status_code == 422 and "valid first name" in res.text


def test_user_names(client):
    login_as(client, ASHA)
    res = client.post("/api/users", json={"full_name": "Neha 2", "email": "neha@crm.test", "password": "Synthetic@2026",
                                          "role": "Salesperson"})
    assert res.status_code == 422 and "valid full name" in res.text


def test_upload_skips_rows_with_unusable_names(client):
    import io
    csv = ("First Name,Last Name,Company,Title,Email\n"
           "Ana,Okafor,Harbor Synthetic,<b>CEO</b>,ana@harbor-synthetic.example\n"
           "Dev,Rao,...,Buyer,dev@harbor-synthetic.example\n"
           "Kai,...,Harbor Synthetic,Buyer,kai@harbor-synthetic.example\n")
    res = client.post("/api/leads/import", data={"dry_run": "true"},
                      files={"file": ("leads.csv", io.BytesIO(csv.encode()), "text/csv")})
    if res.status_code == 404:  # the upload endpoint's path
        res = client.post("/api/leads/upload", data={"dry_run": "true"},
                          files={"file": ("leads.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    reasons = " ".join(e["reason"] for e in body.get("errors", body.get("skipped", [])))
    assert "Enter a company name" in reasons and "last name with at least one letter" in reasons
    assert "title" in " ".join(w["reason"] for w in body.get("warnings", []))


# ---------- the same phone number ----------

def test_a_shared_phone_is_asked_about_once(client):
    first = client.post("/api/leads", json=lead_body())
    assert first.status_code == 201, first.text
    # another person at the same company with the same number: a shared business number, saved after confirming
    other = lead_body(first_name="Dev", last_name="Rao", mailbox="dev", phone="098111 22334")
    res = client.post("/api/leads", json=other)
    assert res.status_code == 409 and "shared business number" in res.json()["detail"]
    found = client.get("/api/leads/phone-matches", params={"phone": "9811122334", "first_name": "Dev", "last_name": "Rao",
                                                           "company": "Harbor Synthetic"}).json()
    assert found["total"] == 1 and not found["blocked"] and found["matches"][0]["same_company"]
    assert client.post("/api/leads", json={**other, "confirm_shared_phone": True}).status_code == 201


def test_the_same_person_with_the_same_phone_is_a_duplicate(client):
    assert client.post("/api/leads", json=lead_body()).status_code == 201
    again = lead_body(mailbox="ana.okafor")  # another email, the same person and number
    res = client.post("/api/leads", json={**again, "confirm_shared_phone": True})
    assert res.status_code == 409 and "already an open lead" in res.json()["detail"]
    # someone else's lead: named only by its owner
    login_as(client, PRIYA)
    found = client.get("/api/leads/phone-matches", params={"phone": "+91 98111 22334", "first_name": "Ana",
                                                           "last_name": "Okafor"}).json()
    assert found["blocked"] and found["matches"][0]["owner_name"] == "Ravi Kumar"


def test_an_edit_checks_a_new_phone_only(client):
    a = client.post("/api/leads", json=lead_body()).json()
    b = client.post("/api/leads", json=lead_body(first_name="Dev", last_name="Rao", mailbox="dev",
                                                  phone="+91 98111 99887")).json()
    assert client.put(f"/api/leads/{b['id']}", json={"title": "Buyer"}).status_code == 200  # phone untouched
    res = client.put(f"/api/leads/{b['id']}", json={"phone": a["phone"]})
    assert res.status_code == 409 and "also on lead Ana Okafor" in res.json()["detail"]
    assert client.put(f"/api/leads/{b['id']}", json={"phone": a["phone"], "confirm_shared_phone": True}).status_code == 200


# ---------- similar company names ----------

@pytest.mark.parametrize("a, b, same", [("TCS", "Tata Consultancy Services", True), ("T.C.S. Ltd", "Tata Consultancy Services Limited", True),
                                         ("IBM", "International Business Machines Corp", True),
                                         ("Tata Consultancy Services", "TCS", True), ("TCS", "Tata Steel", False),
                                         ("Acme", "Acme Corporation", False), ("TCS", "TCS", False),
                                         ("Brightline", "Harbor Freight Labs", False)])
def test_similar_names(a, b, same):
    assert similar_names(a, b) is same


def test_new_account_asks_about_a_similar_name(client):
    login_as(client, ASHA)
    tata = client.post("/api/accounts", json={"name": "Tata Consultancy Services", "industry": "IT Services",
                                              "website": "tcs.com"}).json()
    found = client.get("/api/accounts/duplicates", params={"name": "TCS"}).json()["matches"]
    assert [(m["why"], m["name"]) for m in found] == [("similar", "Tata Consultancy Services")]
    res = client.post("/api/accounts", json={"name": "TCS", "industry": "IT Services"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith('"TCS" may be the same company as the account "Tata Consultancy Services"')
    # another website: another company, never "similar"
    assert client.get("/api/accounts/duplicates", params={"name": "TCS", "website": "techconsult.example"}).json()["matches"] == []
    res = client.post("/api/accounts", json={"name": "TCS", "industry": "IT Services", "confirm_new_company": True})
    assert res.status_code == 201 and res.json()["id"] != tata["id"]


def test_convert_shows_but_never_merges_a_similar_account(client):
    login_as(client, ASHA)
    tata = client.post("/api/accounts", json={"name": "Tata Consultancy Services", "industry": "IT Services"}).json()
    login_as(client, RAVI)
    lead = client.post("/api/leads", json=lead_body(company="TCS", mailbox="ana.tcs")).json()
    check = client.get("/api/opportunities/duplicate-check", params={"lead_id": lead["id"]}).json()
    assert check["account"] is None and [s["name"] for s in check["similar"]] == ["Tata Consultancy Services"]
    matches = client.get("/api/leads/company-matches", params={"company": "TCS"}).json()
    assert any(m.get("similar") and m["company"] == "Tata Consultancy Services" for m in matches["matches"])
    # the user chooses the existing account
    res = convert(client, lead["id"], account_id=tata["id"])
    assert res.status_code in (200, 201), res.text
    assert res.json()["account"]["id"] == tata["id"]
    assert database().query(Account).count() == 1


# ---------- campaigns ----------

@pytest.fixture
def outbox(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_CHECK_DOMAINS", "false")
    mails = []

    def fake(to, subject, body, **kw):
        mails.append({"to": to, **kw})
        return campaigns.Result("sent")
    monkeypatch.setattr(campaigns, "send_one", fake)
    return mails


def test_a_campaign_copies_each_email_to_its_cc(client, outbox):
    lead = client.post("/api/leads", json=lead_body()).json()
    body = {"name": "Synthetic hello", "subject": "Hello {first_name}", "body": "Hi {first_name}, a synthetic note.",
            "lead_ids": [lead["id"]]}
    bad = client.post("/api/campaigns", json={**body, "cc": ["not-an-address"]})
    assert bad.status_code == 422 and "Check the Cc address" in bad.text
    res = client.post("/api/campaigns", json={**body, "cc": [" manager@harbor-synthetic.example", "MANAGER@harbor-synthetic.example"]})
    assert res.status_code == 201, res.text
    created = res.json()
    # one person, due now: it is sending straight away (no "Scheduled" wait)
    assert created["status"] == "Sending" and created["cc"] == ["manager@harbor-synthetic.example"]
    db = database()
    assert db.get(Campaign, created["id"]).started_at is not None
    campaigns.run(db, pause_seconds=0)
    assert outbox == [{"to": lead["email"], "sender_name": "Ravi Kumar", "reply_to": "ravi@crm.test",
                       "unsubscribe": outbox[0]["unsubscribe"], "html": outbox[0]["html"],
                       "cc": ["manager@harbor-synthetic.example"]}]
    assert client.get(f"/api/campaigns/{created['id']}").json()["status"] == "Completed"


def test_cc_is_in_the_email_header(monkeypatch):
    """send_one puts the Cc in the message (Outlook shows the Cc line from the header)."""
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setenv("SMTP_HOST", "smtp.synthetic.example")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("MAIL_PROVIDER", "smtp")
    monkeypatch.setattr(campaigns.smtplib, "SMTP", FakeSMTP)
    result = campaigns.send_one("mia@bluebird.example", "Hello", "Hi Mia", sender_name="Asha Rao",
                                reply_to="asha@crm.test", unsubscribe="https://crm.example/u", cc=["boss@bluebird.example"])
    assert result.outcome == "sent" and sent["msg"]["Cc"] == "boss@bluebird.example"
