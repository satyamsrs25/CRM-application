"""New Lead and Edit Lead (the form, POST / PUT /api/leads): Phone is optional (Vinay's improvements: it used to be
required on New Lead). A given number is still checked for its country like a contact's phone and saved in
international format; on an edit, a new or changed number is checked the same way (an older saved number is left as it
is). Uploads, the AI Assistant and Contact Phone keep the phone optional too. Users: 1 Priya (Manager), 2 Ravi
(Salesperson, default), 3 Asha (Admin). All data is made up."""
import pytest

from app.database import get_db
from app.main import app
from app.models import Lead, Notification
from conftest import login_as

BODY = {"first_name": "Ana", "last_name": "Okafor", "company": "Harbor Synthetic", "source": "Website",
        "email": "ana.okafor@harbor-synthetic.example"}


def db_session():
    return next(app.dependency_overrides[get_db]())


def counts():
    with db_session() as db:
        return db.query(Lead).count(), db.query(Notification).count()


def create(client, **phone):
    return client.post("/api/leads", json={**BODY, **phone})


def test_a_lead_saves_without_any_phone(client):
    # client.request: no "phone" key at all (the test client's default phone is only added to client.post)
    res = client.request("POST", "/api/leads", json=BODY)
    assert res.status_code == 201, res.text
    assert (res.json()["phone"], res.json()["phone_country"], res.json()["region"]) == (None, None, None)


@pytest.mark.parametrize("phone", ["", "   ", None])
def test_a_blank_phone_is_saved_as_no_phone(client, phone):
    res = create(client, phone=phone, phone_country="IN")
    assert res.status_code == 201, res.text
    assert res.json()["phone"] is None
    assert res.json()["region"] == "India"  # a chosen Region stays without a number


@pytest.mark.parametrize("phone, country, message", [
    ("uiadcna", "IN", "Enter a valid phone number for India (+91)."),          # letters
    ("98765 432", "IN", "Enter a valid phone number for India (+91)."),        # too short
    ("6123 4567", "IN", "Enter a valid phone number for India (+91)."),        # valid in Singapore, not India
    ("+1 555", None, "Enter a valid phone number, including its country code after the +."),
])
def test_junk_and_invalid_numbers_are_refused(client, phone, country, message):
    before = counts()
    res = create(client, phone=phone, **({"phone_country": country} if country else {}))
    assert res.status_code == 422 and res.json()["detail"] == message
    assert counts() == before  # no lead, no notification


def test_an_unknown_country_is_refused(client):
    before = counts()
    res = create(client, phone="98765 43210", phone_country="ZZ")
    assert res.status_code == 422 and "Choose the phone number's country." in res.text
    assert counts() == before


@pytest.mark.parametrize("phone, country, saved", [
    ("98765 43210", "IN", "+91 98765 43210"),          # Indian mobile
    ("011 2345 6789", "IN", "+91 11 2345 6789"),       # Indian business landline (Delhi)
    ("98765 43210", None, "+91 98765 43210"),          # no country sent: checked for India, the form's default
    ("(212) 555-0142", "US", "+1 212-555-0142"),       # the chosen country
    ("+44 20 7946 0958", None, "+44 20 7946 0958"),    # its own +country code decides (a London landline)
    ("+44 20 7946 0958", "GB", "+44 20 7946 0958"),
    ("+65 6123 4567", None, "+65 6123 4567"),
])
def test_valid_numbers_of_any_country_are_saved_in_international_format(client, phone, country, saved):
    res = create(client, phone=phone, **({"phone_country": country} if country else {}))
    assert res.status_code == 201, res.text
    assert res.json()["phone"] == saved
    with db_session() as db:
        lead = db.get(Lead, res.json()["id"])
        assert (lead.phone, lead.phone_country) == (saved, country)  # the Region is saved only when it was chosen


def test_a_given_number_cant_skip_the_check(client):
    """There is no flag for skipping it: unknown fields are ignored and an invalid number is still refused."""
    for extra in ({"skip_phone_validation": True}, {"source": "Upload"}, {"workflow": "import"}):
        res = client.request("POST", "/api/leads", json={**BODY, **extra, "phone": "not a number"})
        assert res.status_code == 422, (extra, res.text)


def test_older_leads_without_a_phone_still_save_unrelated_changes(client):
    with db_session() as db:
        lead = Lead(first_name="Old", last_name="Nophone", company="Legacy Synthetic", source="Website", stage="New",
                    owner_id=2, created_by_id=2)
        db.add(lead)
        db.commit()
        lead_id = lead.id
    res = client.put(f"/api/leads/{lead_id}", json={"title": "Buyer", "last_name": "Nophone", "company": "Legacy Synthetic",
                                                   "source": "Website", "phone": None})
    assert res.status_code == 200, res.text
    assert res.json()["phone"] is None and res.json()["title"] == "Buyer"
    assert client.get(f"/api/leads/{lead_id}").status_code == 200


def test_an_edit_checks_a_new_number_and_keeps_an_older_one(client):
    """Editing: a new or changed number is checked for its country and saved in international format, like New Lead;
    an older saved number in another format is left as it is when the edit doesn't change it."""
    lead = create(client, phone="98765 43210", phone_country="IN").json()
    res = client.put(f"/api/leads/{lead['id']}", json={"phone": "Ext. 204 (reception)"})
    assert res.status_code == 422 and res.json()["detail"] == "Enter a valid phone number for India (+91)."
    res = client.put(f"/api/leads/{lead['id']}", json={"phone": "98111 22334"})
    assert res.status_code == 200 and res.json()["phone"] == "+91 98111 22334"
    with db_session() as db:
        db.get(Lead, lead["id"]).phone = "98111-22334 ext 5"  # an older format, as some leads have
        db.commit()
    res = client.put(f"/api/leads/{lead['id']}", json={"title": "Buyer", "phone": "98111-22334 ext 5"})
    assert res.status_code == 200 and res.json()["phone"] == "98111-22334 ext 5"


def test_clearing_a_phone_saves_no_phone_and_keeps_the_region(client):
    lead = create(client, phone="(212) 555-0142", phone_country="US").json()
    for cleared in ("", "   ", None):
        res = client.put(f"/api/leads/{lead['id']}", json={"phone": cleared})
        assert res.status_code == 200, res.text
        assert (res.json()["phone"], res.json()["region"]) == (None, "United States")
        with db_session() as db:
            assert db.get(Lead, lead["id"]).phone is None  # not "" or spaces


def test_contact_phone_stays_optional(client):
    account = client.post("/api/accounts", json={"name": "Phone Optional Synthetic", "industry": "Logistics"}).json()
    res = client.post("/api/contacts", json={"first_name": "Mia", "last_name": "Noph", "email": "mia@phone-optional.example",
                                             "account_id": account["id"]})
    assert res.status_code == 201, res.text
    assert res.json()["phone"] is None


def test_uploads_keep_the_phone_optional(client):
    import csv
    import io
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Last Name", "Company", "Email"],
                               ["Up", "Loaded", "Upload Synthetic Co", "up.loaded@upload-synthetic.example"]])
    res = client.post("/api/leads/import", files={"file": ("x.csv", out.getvalue().encode(), "text/csv")},
                      data={"dry_run": "false"})
    assert res.status_code == 200 and res.json()["created"] == 1, res.text


def test_a_manager_and_the_admin_create_leads_without_a_phone_too(client):
    for user_id, owner in ((1, None), (3, 2)):
        res = login_as(client, user_id).request("POST", "/api/leads", json={**BODY, **({"owner_id": owner} if owner else {}),
                                                                           "email": f"u{user_id}@harbor-synthetic.example"})
        assert res.status_code == 201, res.text
        assert res.json()["phone"] is None
