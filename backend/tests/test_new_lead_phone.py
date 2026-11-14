"""New Lead (the form, POST /api/leads) needs a valid Phone, checked for its country like a contact's phone. Uploads,
the AI Assistant, editing and Contact Phone keep the phone optional. Users: 1 Priya (Manager), 2 Ravi (Salesperson,
default), 3 Asha (Admin). All data is made up."""
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


def test_a_request_without_any_phone_is_refused(client):
    before = counts()
    # client.request: no "phone" key at all (the test client's default phone is only added to client.post)
    res = client.request("POST", "/api/leads", json=BODY)
    assert res.status_code == 422 and res.json()["detail"] == "Enter the lead's phone number."
    assert counts() == before  # no lead, no notification


@pytest.mark.parametrize("phone, country, message", [
    ("", "IN", "Enter the lead's phone number."),
    ("   ", "IN", "Enter the lead's phone number."),
    (None, "IN", "Enter the lead's phone number."),
    ("uiadcna", "IN", "Enter a valid phone number for India (+91)."),          # letters
    ("98765 432", "IN", "Enter a valid phone number for India (+91)."),        # too short
    ("6123 4567", "IN", "Enter a valid phone number for India (+91)."),        # valid in Singapore, not India
    ("+1 555", None, "Enter a valid phone number, including its country code after the +."),
    ("98765 43210", "ZZ", "Choose the phone number's country."),
])
def test_blank_junk_and_invalid_numbers_are_refused(client, phone, country, message):
    before = counts()
    res = create(client, phone=phone, **({"phone_country": country} if country else {}))
    assert res.status_code == 422 and res.json()["detail"] == message
    assert counts() == before


@pytest.mark.parametrize("phone, country, saved", [
    ("98765 43210", "IN", "+91 98765 43210"),          # Indian mobile
    ("011 2345 6789", "IN", "+91 11 2345 6789"),       # Indian business landline (Delhi)
    ("98765 43210", None, "+91 98765 43210"),          # no country sent: India, the form's default
    ("(212) 555-0142", "US", "+1 212-555-0142"),       # the chosen country
    ("+44 20 7946 0958", "IN", "+44 20 7946 0958"),    # its own +country code decides (a London landline)
    ("+65 6123 4567", "IN", "+65 6123 4567"),
])
def test_valid_numbers_of_any_country_are_saved_in_international_format(client, phone, country, saved):
    res = create(client, phone=phone, **({"phone_country": country} if country else {}))
    assert res.status_code == 201, res.text
    assert res.json()["phone"] == saved
    with db_session() as db:
        lead = db.get(Lead, res.json()["id"])
        assert lead.phone == saved  # phone_country isn't stored


def test_the_form_cant_switch_the_rule_off(client):
    """There is no flag for skipping it: unknown fields are ignored and the phone is still required."""
    for extra in ({"skip_phone_validation": True}, {"source": "Upload"}, {"workflow": "import"}):
        res = client.request("POST", "/api/leads", json={**BODY, **extra})
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


def test_an_edit_keeps_the_phone_as_typed(client):
    """Editing keeps the earlier rule (optional, as typed): saved numbers aren't rewritten."""
    lead = create(client, phone="98765 43210", phone_country="IN").json()
    res = client.put(f"/api/leads/{lead['id']}", json={"phone": "Ext. 204 (reception)"})
    assert res.status_code == 200 and res.json()["phone"] == "Ext. 204 (reception)"


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


def test_a_manager_and_the_admin_need_a_phone_too(client):
    for user_id, owner in ((1, None), (3, 2)):
        res = login_as(client, user_id).request("POST", "/api/leads", json={**BODY, **({"owner_id": owner} if owner else {}),
                                                                           "email": f"u{user_id}@harbor-synthetic.example"})
        assert res.status_code == 422 and res.json()["detail"] == "Enter the lead's phone number."
