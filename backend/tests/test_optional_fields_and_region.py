"""Vinay's improvements 3-5: Last Name optional, Phone optional, and Region (the country chosen beside the phone).

- Last Name is optional on leads (New / Edit Lead, uploads, the API), contacts (New Contact, New Opportunity's new
  contact) and in conversion; a record still needs a name (First Name stays required where it was; an upload row
  needs a first or last name). An absent last name is stored as "" and the full name is never "Asha None".
- Phone is optional; a given number is checked as before; blank numbers never match each other.
- Region is saved only when chosen (phone_country), as one named country even for shared codes (+1), never guessed,
  shown on pooled leads (their email, phone and LinkedIn stay hidden), and in the lead upload and download.
Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin). All data is made up."""
import csv
import io
import json

import phonenumbers
import pytest
from openpyxl import load_workbook

from app import campaigns
from app.database import get_db
from app.main import app
from app.models import Contact, Lead, Notification, User
from app.regions import country_name, region_from_text
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)

ASHA, RAVI = 3, 2
TASK = {"title": "Synthetic follow-up", "due_date": "2030-01-15T10:00:00"}


def db():
    return next(app.dependency_overrides[get_db]())


def new_lead(client, **fields):
    body = {"first_name": "Asha", "company": "Solo Synthetic Co", "source": "Website",
            "email": f"{(fields.get('first_name') or 'asha').lower()}@solo-synthetic.example", **fields}
    return client.request("POST", "/api/leads", json=body)  # no default phone (client.post adds one)


def account(client, name="Region Synthetic Ltd"):
    res = client.post("/api/accounts", json={"name": name, "industry": "Logistics"})
    assert res.status_code == 201, res.text
    return res.json()


def stored(model, record_id):
    with db() as s:
        row = s.get(model, record_id)
        s.expunge(row)
        return row


def national(region):
    """A valid national-format number for this country (libphonenumber's own example)."""
    return phonenumbers.format_number(phonenumbers.example_number(region), phonenumbers.PhoneNumberFormat.NATIONAL)


# ---------- Last Name optional ----------

def test_a_lead_without_a_last_name_has_a_clean_name_everywhere(client):
    res = new_lead(client, last_name=None)
    assert res.status_code == 201, res.text
    lead = res.json()
    assert (lead["first_name"], lead["last_name"], lead["name"]) == ("Asha", "", "Asha")
    assert stored(Lead, lead["id"]).last_name == ""  # the column stays NOT NULL
    for first, omitted in (("Bina", {}), ("Cara", {"last_name": ""}), ("Dina", {"last_name": "   "})):
        other = new_lead(client, first_name=first, **omitted).json()  # missing, empty or only spaces: the same
        assert (other["last_name"], other["name"]) == ("", first), other
    # lists, search and the owner's notification use the same name (no "None", no trailing space)
    found = client.get("/api/leads/page", params={"view": "all", "search": "Asha"}).json()["items"]
    assert [l["name"] for l in found] == ["Asha"]
    with db() as s:
        messages = [n.message for n in s.query(Notification).filter_by(user_id=RAVI)]
    assert any("Lead: Asha\n" in m for m in messages) and not any("None" in m for m in messages)


def test_new_lead_still_needs_a_first_name(client):
    res = new_lead(client, first_name=None, last_name="Rao", email="rao@solo-synthetic.example")
    assert res.status_code == 422 and "Enter the lead's first name." in res.text


def test_an_edit_may_clear_the_last_name_but_never_leaves_a_lead_nameless(client):
    lead = new_lead(client, last_name="Rao").json()
    res = client.put(f"/api/leads/{lead['id']}", json={"last_name": ""})
    assert res.status_code == 200 and (res.json()["last_name"], res.json()["name"]) == ("", "Asha")
    res = client.put(f"/api/leads/{lead['id']}", json={"last_name": None})
    assert res.status_code == 200 and res.json()["name"] == "Asha"
    # an older lead with only a last name (uploads allowed that): its last name can't be cleared too
    with db() as s:
        old = Lead(last_name="Only", company="Older Synthetic", source="Upload", stage="New", owner_id=RAVI)
        s.add(old)
        s.commit()
        old_id = old.id
    res = client.put(f"/api/leads/{old_id}", json={"last_name": ""})
    assert res.status_code == 400 and res.json()["detail"] == "Enter a first name or last name."
    assert stored(Lead, old_id).last_name == "Only"
    assert client.put(f"/api/leads/{old_id}", json={"title": "Buyer"}).status_code == 200  # unrelated edits still save
    # a first name can't be cleared once it is there (as before)
    assert client.put(f"/api/leads/{lead['id']}", json={"first_name": ""}).status_code == 400


def test_a_contact_without_a_last_name(client):
    acc = account(client)
    res = client.post("/api/contacts", json={"first_name": "Mira", "email": "mira@region-synthetic.example",
                                             "account_id": acc["id"]})
    assert res.status_code == 201, res.text
    assert (res.json()["last_name"], res.json()["full_name"]) == ("", "Mira")
    # one person, one contact: the same name on the same account is refused, whatever parts the name has
    again = client.post("/api/contacts", json={"first_name": "Mira", "last_name": "  ", "email": "mira2@region-synthetic.example",
                                               "account_id": acc["id"]})
    assert again.status_code == 409 and "has the same name on this account" in again.json()["detail"]
    assert client.post("/api/contacts", json={"first_name": "Mira", "last_name": "Shah", "account_id": acc["id"],
                                              "email": "mira.shah@region-synthetic.example"}).status_code == 201
    listed = client.get("/api/contacts", params={"account_id": acc["id"]}).json()
    assert sorted(c["full_name"] for c in listed) == ["Mira", "Mira Shah"]


def test_a_new_opportunity_contact_without_a_last_name_and_with_a_region(client):
    res = client.post("/api/opportunities", json={
        "name": "Synthetic CRM rollout", "note": "Synthetic: the customer asked for a proposal", "task": TASK,
        "account_name": "Opportunity Synthetic Co", "contact_first_name": "Noor", "contact_email": "noor@opp-synthetic.example",
        "contact_phone": national("CA"), "contact_phone_country": "CA"})
    assert res.status_code == 201, res.text
    contact = res.json()["contact"]
    assert (contact["full_name"], contact["last_name"], contact["phone_country"], contact["region"]) == ("Noor", "", "CA", "Canada")


def test_conversion_keeps_a_missing_last_name_and_the_region(client):
    lead = new_lead(client, first_name="Kiran", phone=national("US"), phone_country="US").json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert res.status_code == 200, res.text
    contact = res.json()["contact"]
    assert (contact["full_name"], contact["last_name"], contact["phone"]) == ("Kiran", "", lead["phone"])
    assert (contact["phone_country"], contact["region"]) == ("US", "United States")


def test_campaign_merge_fields_and_drafts_without_a_last_name(client):
    lead = new_lead(client, first_name="Tara").json()
    with db() as s:
        row = s.get(Lead, lead["id"])
        sender = s.get(User, RAVI)
        assert campaigns.fill("Hi {first_name} | {full_name} | [{last_name}]", row, sender) == "Hi Tara | Tara | []"
        older = Lead(last_name="Menon", company="Older Synthetic", source="Upload", stage="New", owner_id=RAVI)
        assert campaigns.fill("Hi {first_name} | {full_name}", older, sender) == "Hi Menon | Menon"
    draft = client.post("/api/emails/draft", json={"record_field": "lead_id", "record_id": lead["id"],
                                                   "instructions": "Thank them for the call."})
    assert draft.status_code == 200, draft.text
    assert draft.json()["body"].startswith("Hi Tara,") and "None" not in draft.json()["body"]


# ---------- Phone optional ----------

def test_leads_without_phones_never_match_each_other(client):
    first = new_lead(client, first_name="Same", last_name="Person", email="same1@solo-synthetic.example")
    second = new_lead(client, first_name="Same", last_name="Person", email="same2@solo-synthetic.example", phone="  ")
    assert (first.status_code, second.status_code) == (201, 201)
    blank = client.get("/api/leads/phone-matches", params={"phone": "   "}).json()
    assert (blank["total"], blank["blocked"]) == (0, False)  # a blank number is never compared
    # a populated duplicate is still refused for the same person (the policy is unchanged)
    one = new_lead(client, first_name="Dup", last_name="Person", email="dup1@solo-synthetic.example", phone="98111 22334")
    two = new_lead(client, first_name="Dup", last_name="Person", email="dup2@solo-synthetic.example", phone="+91 98111 22334")
    assert one.status_code == 201 and two.status_code == 409 and "This person is already an open lead" in two.json()["detail"]


# ---------- Region ----------

@pytest.mark.parametrize("region, name", [("IN", "India"), ("US", "United States"), ("CA", "Canada"), ("JM", "Jamaica")])
def test_the_chosen_region_is_saved_and_shared_codes_stay_apart(client, region, name):
    res = new_lead(client, first_name=f"Reg{region}", phone=national(region), phone_country=region)
    assert res.status_code == 201, res.text
    assert (res.json()["phone_country"], res.json()["region"]) == (region, name)
    assert stored(Lead, res.json()["id"]).phone_country == region
    again = client.get(f"/api/leads/{res.json()['id']}").json()  # after a reload
    assert (again["phone_country"], again["region"]) == (region, name)


def test_a_number_valid_in_one_plus_one_country_isnt_taken_for_another(client):
    us, ca = national("US"), national("CA")
    if phonenumbers.is_valid_number_for_region(phonenumbers.parse(us, "CA"), "CA"):
        pytest.skip("the example numbers happen to be valid in both")
    res = new_lead(client, first_name="Wrong", phone=us, phone_country="CA")
    assert res.status_code == 422 and res.json()["detail"] == "Enter a valid phone number for Canada (+1)."
    assert new_lead(client, first_name="Right", phone=ca, phone_country="CA").json()["region"] == "Canada"


# US, Canada and Jamaica share +1. A number is checked against the chosen country's own numbering plan (Google
# libphonenumber's per-country patterns, is_valid_number_for_region), typed with or without +1: a Toronto (416) number
# is Canadian, a New York (212) one American, an 876 one Jamaican, and the shared toll-free numbers (800, 888) are valid
# for all three. Nothing maps +1 to the United States.
NANP = [("(212) 555-0142", {"US"}), ("(416) 555-0142", {"CA"}), ("(876) 523-0123", {"JM"}), ("(876) 210-1234", {"JM"}),
        ("(800) 234-5678", {"US", "CA", "JM"}), ("(888) 226-6362", {"US", "CA", "JM"})]


@pytest.mark.parametrize("number, home", NANP)
@pytest.mark.parametrize("region", ["US", "CA", "JM"])
@pytest.mark.parametrize("typed", ["national", "+1"])
def test_us_canada_and_jamaica_each_take_their_own_numbers_typed_either_way(client, number, home, region, typed):
    text = number if typed == "national" else "+1 " + number
    res = new_lead(client, first_name="Nanp", email=f"nanp.{region.lower()}.{len(text)}@solo-synthetic.example",
                   phone=text, phone_country=region)
    name = {"US": "United States", "CA": "Canada", "JM": "Jamaica"}[region]
    if region in home:
        assert res.status_code == 201, res.text
        assert (res.json()["phone"].startswith("+1 "), res.json()["region"]) == (True, name)
    elif typed == "national":
        assert res.status_code == 422 and res.json()["detail"] == f"Enter a valid phone number for {name} (+1)."
    else:  # the same calling code, but not this country's number: the Region must be the number's country
        assert res.status_code == 422
        assert res.json()["detail"] == f"This number isn't valid for the Region, {name} (+1). Choose the number's country."


def test_without_a_region_a_plus_one_number_is_checked_for_its_own_plan_only(client):
    """No Region chosen: a +1 number is valid wherever +1 says (as before), and no Region is saved or guessed."""
    res = new_lead(client, first_name="Free", phone="+1 416 555 0142")
    assert res.status_code == 201 and (res.json()["phone"], res.json()["region"]) == ("+1 416-555-0142", None)


def test_a_plus_code_must_belong_to_the_chosen_region(client):
    res = new_lead(client, first_name="Mismatch", phone="+1 212 555 0142", phone_country="IN")
    assert res.status_code == 422
    assert res.json()["detail"] == ("This number's country code is +1, but the Region is India (+91). "
                                    "Choose the number's country.")
    assert new_lead(client, first_name="Usa", phone="+1 212 555 0142", phone_country="US").json()["region"] == "United States"
    acc = account(client)
    contact = client.post("/api/contacts", json={"first_name": "Lee", "email": "lee@region-synthetic.example",
                                                 "account_id": acc["id"], "phone": "+44 20 7946 0958", "phone_country": "IN"})
    assert contact.status_code == 422 and "the Region is India (+91)" in contact.text
    # the same per-country rule for contacts: a Toronto number isn't saved with Region United States
    contact = client.post("/api/contacts", json={"first_name": "Lia", "email": "lia@region-synthetic.example",
                                                 "account_id": acc["id"], "phone": "+1 416 555 0142", "phone_country": "US"})
    assert contact.status_code == 422 and "isn't valid for the Region, United States (+1)" in contact.text


def test_a_region_without_a_phone_and_none_when_nothing_was_chosen(client):
    chosen = new_lead(client, first_name="NoPhone", phone_country="US").json()
    assert (chosen["phone"], chosen["region"]) == (None, "United States")
    none = new_lead(client, first_name="Nothing").json()
    assert (none["phone_country"], none["region"]) == (None, None)  # never India by default
    plus = new_lead(client, first_name="Plus", phone="+44 20 7946 0958").json()
    assert (plus["phone"], plus["region"]) == ("+44 20 7946 0958", None)  # not guessed from the number either


def test_editing_the_region(client):
    lead = new_lead(client, first_name="Edit", phone="98765 43210", phone_country="IN").json()
    lead_id = lead["id"]
    res = client.put(f"/api/leads/{lead_id}", json={"phone_country": "US"})  # the +91 number stays: refused
    assert res.status_code == 422 and "the Region is United States (+1)" in res.json()["detail"]
    res = client.put(f"/api/leads/{lead_id}", json={"phone": national("US"), "phone_country": "US"})
    assert res.status_code == 200 and (res.json()["region"], res.json()["phone"].startswith("+1")) == ("United States", True)
    res = client.put(f"/api/leads/{lead_id}", json={"phone": ""})  # clearing the phone keeps the chosen Region
    assert res.status_code == 200 and (res.json()["phone"], res.json()["region"]) == (None, "United States")
    res = client.put(f"/api/leads/{lead_id}", json={"title": "Buyer"})  # an edit that doesn't send it keeps it
    assert res.json()["region"] == "United States"
    res = client.put(f"/api/leads/{lead_id}", json={"phone_country": None})  # cleared on purpose
    assert res.status_code == 200 and res.json()["region"] is None
    assert client.put(f"/api/leads/{lead_id}", json={"phone_country": "ZZ"}).status_code == 422


def test_older_records_keep_an_empty_region(client):
    with db() as s:
        old = Lead(first_name="Old", last_name="Phone", phone="+91 98765 43210", company="Older Synthetic", source="Website",
                   stage="New", owner_id=RAVI)
        s.add(old)
        s.commit()
        old_id, updated = old.id, old.updated_at
    lead = client.get(f"/api/leads/{old_id}").json()
    assert (lead["phone"], lead["phone_country"], lead["region"]) == ("+91 98765 43210", None, None)  # not guessed
    assert stored(Lead, old_id).updated_at == updated  # reading changes nothing
    assert client.put(f"/api/leads/{old_id}", json={"title": "Buyer", "phone": "+91 98765 43210"}).json()["region"] is None


def test_a_pooled_leads_region_is_shown_while_its_contact_details_stay_hidden(client):
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Company", "Email", "Phone", "Region (Country)"],
                               ["Pia", "Pool Region Co", "pia@pool-region.example", "+91 98765 43210", "India"]])
    assert login_as(client, ASHA).post("/api/leads/import", files={"file": ("p.csv", out.getvalue().encode(), "text/csv")},
                                       data={"dry_run": "false"}).json()["created"] == 1
    pooled = login_as(client, ASHA).get("/api/leads/page", params={"view": "unassigned"}).json()["items"][0]
    assert pooled["region"] == "India"  # the Admin sees it
    seen = login_as(client, RAVI).get(f"/api/leads/{pooled['id']}").json()  # a Salesperson can only request it
    assert (seen["contact_hidden"], seen["phone_country"], seen["region"]) == (True, "IN", "India")  # the country only
    assert (seen["phone"], seen["email"], seen["linkedin_url"]) == (None, None, None)  # still hidden, as before


# ---------- uploads and downloads ----------

def upload(client, header, rows, dry_run=False, name="names.csv"):
    out = io.StringIO()
    csv.writer(out).writerows([header, *rows])
    res = login_as(client, ASHA).post("/api/leads/import", files={"file": (name, out.getvalue().encode(), "text/csv")},
                                      data={"dry_run": "true" if dry_run else "false"})
    assert res.status_code == 200, res.text
    return res.json()


def leads_by_email():
    with db() as s:
        return {l.email: l for l in s.query(Lead)}


def test_an_upload_needs_a_first_or_last_name_and_keeps_the_names_as_given(client):
    """Base 8c419f5 skipped a row without a last name, or with a last name that has no letter ("..."); it never checked
    the first name. Now either name is enough; a given last name is still checked the same way, and nothing the file
    gives is dropped."""
    body = upload(client, ["First Name", "Last Name", "Company", "Email"], [
        ["Arjun", "", "Name Synthetic Co", "arjun@name-synthetic.example"],     # first name only
        ["", "Menon", "Name Synthetic Co", "menon@name-synthetic.example"],     # last name only
        ["", "", "Name Synthetic Co", "nobody@name-synthetic.example"],         # no name: skipped
        ["Dev", "...", "Name Synthetic Co", "dev@name-synthetic.example"],      # a last name with no letter: skipped, as before
        ["X1", "", "Name Synthetic Co", "x1@name-synthetic.example"],           # the first name isn't checked, as before
    ])
    assert body["created"] == 3
    assert [(e["row"], e["reason"]) for e in body["errors"]] == [
        (4, "Name is missing (a first or last name)"), (5, "Enter a last name with at least one letter.")]
    assert body["warnings"] == []  # no name part was left out
    got = {email: (l.first_name, l.last_name, l.name) for email, l in leads_by_email().items()}
    assert got == {"arjun@name-synthetic.example": ("Arjun", "", "Arjun"),
                   "menon@name-synthetic.example": (None, "Menon", "Menon"),
                   "x1@name-synthetic.example": ("X1", "", "X1")}


def test_a_file_with_only_a_first_name_column_is_accepted(client):
    assert upload(client, ["First Name", "Company"], [["Ola", "First Only Synthetic"]], dry_run=True)["ready"] == 1
    res = login_as(client, ASHA).post("/api/leads/import", data={"dry_run": "true"},
                                      files={"file": ("x.csv", b"Title,Company\nBuyer,No Name Co\n", "text/csv")})
    assert res.status_code == 400 and res.json()["detail"] == "The file needs a 'First Name', 'Last Name' or 'Name' column."


def test_state_and_region_columns_still_build_the_location_and_never_set_the_country_region(client):
    """An older file's State or Region column is a state, province or territory (even a two-letter one that is also a
    country code: CA is California, IN is Indiana): it goes into the Location exactly as before (City, State,
    Country; the first of State / Region when a file has both) and never sets the Region."""
    body = upload(client, ["First Name", "Company", "Email", "City", "Region", "Country"], [
        ["Cal", "State Up Co", "cal@state-up.example", "San Jose", "CA", "United States"],
        ["Ind", "State Up Co", "ind@state-up.example", "Indianapolis", "IN", ""],
        ["Kar", "State Up Co", "kar@state-up.example", "Bengaluru", "Karnataka", "India"],
        ["Cty", "State Up Co", "cty@state-up.example", "", "India", ""],
    ])
    assert body["created"] == 4 and body["warnings"] == []
    got = {l.first_name: (l.location, l.phone_country) for l in leads_by_email().values()}
    assert got == {"Cal": ("San Jose, CA, United States", None), "Ind": ("Indianapolis, IN", None),
                   "Kar": ("Bengaluru, Karnataka, India", None), "Cty": ("India", None)}
    both = upload(client, ["First Name", "Company", "Email", "City", "Region", "State"],
                  [["Two", "State Up Co", "two@state-up.example", "Pune", "West", "Maharashtra"]], name="both.csv")
    assert both["created"] == 1 and leads_by_email()["two@state-up.example"].location == "Pune, West"  # the first, as before


def test_the_region_country_column_sets_the_region_and_never_guesses_a_shared_code(client):
    body = upload(client, ["First Name", "Company", "Email", "City", "State", "Region (Country)"], [
        ["In", "Region Up Co", "in@region-up.example", "Pune", "Maharashtra", "India"],
        ["Us", "Region Up Co", "us@region-up.example", "Austin", "Texas", "US"],
        ["Ca", "Region Up Co", "ca@region-up.example", "Toronto", "Ontario", "CA"],      # in this column CA is Canada
        ["Pl", "Region Up Co", "pl@region-up.example", "", "", "+1"],                    # +1: shared by 25 countries
        ["Ip", "Region Up Co", "ip@region-up.example", "", "", "+91"],                   # +91: only India
        ["Em", "Region Up Co", "em@region-up.example", "", "", "EMEA"],                  # not a country
    ])
    assert body["created"] == 6
    got = {l.first_name: (l.phone_country, l.location) for l in leads_by_email().values()}
    assert got == {"In": ("IN", "Pune, Maharashtra"), "Us": ("US", "Austin, Texas"), "Ca": ("CA", "Toronto, Ontario"),
                   "Pl": (None, None), "Ip": ("IN", None), "Em": (None, None)}
    notes = {w["row"]: w["reason"] for w in body["warnings"]}
    assert "+1 is shared by several countries" in notes[5] and "'EMEA': not a country" in notes[7]
    alias = upload(client, ["First Name", "Company", "Email", "Phone Country"],
                   [["Ph", "Region Up Co", "ph@region-up.example", "Jamaica"]], name="alias.csv")
    assert alias["created"] == 1 and leads_by_email()["ph@region-up.example"].phone_country == "JM"


def test_a_download_reads_back_with_its_location_and_region(client):
    """Download, then upload the same file (the emails changed, or they'd be skipped as duplicates): each lead comes
    back with the same Location (a state in it stays there) and the same Region."""
    upload(client, ["First Name", "Company", "Email", "City", "State", "Country", "Region (Country)"], [
        ["Tex", "Trip Synthetic Co", "tex@trip-synthetic.example", "Austin", "Texas", "United States", "United States"],
        ["Kar", "Trip Synthetic Co", "kar@trip-synthetic.example", "Bengaluru", "Karnataka", "", ""],
        ["Ont", "Trip Synthetic Co", "ont@trip-synthetic.example", "Toronto", "ON", "", "Canada"],
    ])
    new_lead(client, first_name="Form", phone=national("JM"), phone_country="JM", location="Kingston, Saint Andrew")
    before = {l.first_name: (l.location, l.phone_country) for l in leads_by_email().values()}
    res = login_as(client, ASHA).get("/api/leads/export", params={"reason": "Synthetic round trip", "format": "xlsx"})
    assert res.status_code == 200
    book = load_workbook(io.BytesIO(res.content))
    sheet = book.worksheets[0]
    header = [c.value for c in sheet[1]]
    assert header[header.index("Phone") + 1] == "Region (Country)" and "Location" in header
    region = {r[header.index("First Name")]: r[header.index("Region (Country)")] for r in sheet.iter_rows(min_row=2, values_only=True)}
    assert region == {"Tex": "United States", "Kar": None, "Ont": "Canada", "Form": "Jamaica"}
    email_col = header.index("Email") + 1
    for row in range(2, sheet.max_row + 1):
        cell = sheet.cell(row=row, column=email_col)
        cell.value = "again." + cell.value
    out = io.BytesIO()
    book.save(out)
    res = login_as(client, ASHA).post("/api/leads/import", data={"dry_run": "false"},
                                      files={"file": ("again.xlsx", out.getvalue(),
                                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code == 200 and res.json()["created"] == 4, res.text
    after = {l.first_name: (l.location, l.phone_country) for e, l in leads_by_email().items() if e.startswith("again.")}
    assert after == before


def test_region_names_and_codes():
    assert [country_name(c) for c in ("IN", "US", "CA", "XK", None, "ZZ")] == [
        "India", "United States", "Canada", "Kosovo", None, None]
    assert region_from_text("in") == ("IN", "") and region_from_text("+44")[0] is None  # +44: the UK and Crown dependencies
    assert region_from_text("") == (None, "") and region_from_text("EMEA") == (None, "")


def test_the_migration_only_adds_empty_columns():
    from pathlib import Path
    main = Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert '("leads", "phone_country", "VARCHAR(2)"), ("contacts", "phone_country", "VARCHAR(2)")' in main
    assert "UPDATE leads SET phone_country" not in main and "UPDATE contacts SET phone_country" not in main
    schema = Path("/database/schema.sql").read_text(encoding="utf-8")
    assert schema.count("phone_country VARCHAR(2)") == 2


# ---------- the AI Assistant's leads: the same phone checks and duplicate-phone rule as New Lead ----------
# (the model is a scripted stand-in: no AI service is called, and the AI settings are untouched)

def assistant_does(client, ai, tool_name, **args):
    """The model asks for this tool; returns the tool's answer to it (with "error" when it was refused)."""
    script, seen = ai
    script.extend([[call(tool_name, **args)], "Done."])
    assert client.post("/api/assistant/chat", json={"message": "Synthetic request"}).status_code == 200
    return json.loads([m for m in seen[-1] if m["role"] == "tool"][-1]["content"])


def assistant_lead(client, ai, **args):
    return assistant_does(client, ai, "create_lead", **{"company": "Assist Phone Synthetic", "source": "Website", **args})


def test_the_assistants_new_leads_follow_the_phone_rules(client, ai):
    # no phone: allowed (and no Region)
    assert "error" not in assistant_lead(client, ai, first_name="Nophone", email="nophone@assist-phone.example")
    # a given number: checked as the form does (India when no country was named) and saved in international format
    assert "error" not in assistant_lead(client, ai, first_name="Valid", email="valid@assist-phone.example", phone="98111 22334")
    refused = assistant_lead(client, ai, first_name="Bad", email="bad@assist-phone.example", phone="12345")
    assert refused["error"] == "Enter a valid phone number for India (+91)."
    # the country the user named is the Region (checked for it and saved); a Toronto number isn't a US one
    assert "error" not in assistant_lead(client, ai, first_name="Usnum", email="usnum@assist-phone.example",
                                         phone="(212) 555-0142", phone_country="US")
    wrong = assistant_lead(client, ai, first_name="Tor", email="tor@assist-phone.example", phone="+1 416 555 0142",
                           phone_country="US")
    assert "isn't valid for the Region, United States (+1)" in wrong["error"]
    got = {l.email: (l.phone, l.phone_country) for l in leads_by_email().values()}
    assert got == {"nophone@assist-phone.example": (None, None),
                   "valid@assist-phone.example": ("+91 98111 22334", None),  # no Region invented
                   "usnum@assist-phone.example": ("+1 212-555-0142", "US")}


def test_the_assistant_follows_the_duplicate_phone_rule(client, ai):
    assert "error" not in assistant_lead(client, ai, first_name="Mira", last_name="Shah", email="mira@assist-phone.example",
                                         phone="+91 98111 22334")
    same = assistant_lead(client, ai, first_name="Mira", last_name="Shah", email="mira2@assist-phone.example",
                          phone="098111 22334")
    assert same["error"].startswith("This person is already an open lead with this phone number")
    other = assistant_lead(client, ai, first_name="Ravi", last_name="Iyer", email="ravi.iyer@assist-phone.example",
                           phone="98111 22334")
    assert other["error"].startswith("This phone number is also on")  # asked once, like the form
    shared = assistant_lead(client, ai, first_name="Ravi", last_name="Iyer", email="ravi.iyer@assist-phone.example",
                            phone="98111 22334", confirm_shared_phone=True)  # the user said it's a shared line
    assert "error" not in shared
    assert sorted(leads_by_email()) == ["mira@assist-phone.example", "ravi.iyer@assist-phone.example"]


def test_the_assistant_leaves_an_older_leads_phone_as_it_is(client, ai):
    with db() as s:
        old = Lead(first_name="Old", last_name="Format", phone="98111-22334 ext 5", company="Older Synthetic",
                   source="Website", stage="New", owner_id=RAVI)
        s.add(old)
        s.commit()
        old_id = old.id
    assert "error" not in assistant_does(client, ai, "update_lead", lead_id=old_id, title="Buyer")
    lead = stored(Lead, old_id)
    assert (lead.title, lead.phone, lead.phone_country) == ("Buyer", "98111-22334 ext 5", None)
    changed = assistant_does(client, ai, "update_lead", lead_id=old_id, phone="not a number")
    assert changed["error"] == "Enter a valid phone number for India (+91)." and stored(Lead, old_id).phone == "98111-22334 ext 5"
