"""vikram-crm-followups: the Admin converts leads like Managers and Salespeople; LinkedIn as a Lead Source; what an
"Other" source is; First Name on new leads; optional company links; older leads stay viewable and editable.
All data is made up. Email is recorded instead of sent, and no AI or Apollo service is called (the AI is scripted)."""
import csv
import inspect
import io
import itertools
import json
import re
from pathlib import Path
from typing import get_args

import pytest
from sqlalchemy import select

from app import assistant, constants, main, models, schemas
from app.models import Account, Contact, Lead, Opportunity, Task
from app.security import Acting
from conftest import login_as
from test_assistant import ai, call  # noqa: F401 (ai: a scripted stand-in for the AI model)
from test_mandatory_stage_notes import sent, snapshot  # noqa: F401 (sent: autouse, records email instead of sending)
from test_opportunity_attachments import ASHA, PRIYA, RAVI, add_salesperson, db_session

N = itertools.count(1)
TASK = {"title": "Synthetic first deal task", "due_date": "2030-01-15T10:00:00"}
DONE = {"completed_stages": ["New", "Nurturing", "Demo"], "expected_value": 2500}
SOURCES = [s for s in constants.LEAD_SOURCES if s != "Upload"]  # the New Lead form's choices


def lead_body(**extra):
    n = next(N)
    return {"first_name": "Nia", "last_name": f"Synthetic{n}", "company": f"Followup Co {n}",
            "email": f"followup{n}@example.test", "source": "Website", "welcome_email": False} | extra


def new_lead(client, **extra):
    res = client.post("/api/leads", json=lead_body(**extra))
    assert res.status_code == 201, res.text
    return res.json()


def convert(client, lead_id, **body):
    return client.post(f"/api/leads/{lead_id}/convert", json={"task": TASK, **DONE, "note": "Budget approved", **body})


def detail(res) -> str:
    body = res.json()["detail"]
    return body if isinstance(body, str) else " ".join(e["msg"] for e in body)


def legacy_lead(**fields) -> int:
    """A lead saved before these rules (straight into the database, as older records are)."""
    with db_session() as db:
        lead = Lead(**({"first_name": None, "last_name": "Legacy", "company": "Old Records Co", "source": "Other",
                        "source_detail": None, "linkedin_url": None, "company_website": None,
                        "company_linkedin_url": None, "email": None, "owner_id": RAVI, "stage": "New"} | fields))
        db.add(lead)
        db.commit()
        return lead.id


# ---------- 1. Admin lead conversion ----------

def test_the_admin_converts_an_eligible_lead_with_the_same_flow_and_ownership(client, sent):
    lead = new_lead(client)  # Ravi's
    res = convert(login_as(client, ASHA), lead["id"], opportunity_name="Synthetic Admin Deal")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["lead"]["stage"] == "Converted"
    assert out["opportunity"]["stage"] == "Opportunity" and out["opportunity"]["name"] == "Synthetic Admin Deal"
    # everything stays with the lead's owner (the Admin isn't made the owner); the new task goes to the owner too
    assert out["opportunity"]["owner_id"] == RAVI and out["new_task"]["owner_id"] == RAVI
    with db_session() as db:
        opp = db.get(Opportunity, out["opportunity"]["id"])
        assert db.get(Account, opp.account_id).owner_id == RAVI
        assert db.get(Contact, opp.primary_contact_id).owner_id == RAVI
        assert opp.lead_id == lead["id"]
    history = client.get(f"/api/leads/{lead['id']}/history").json()
    assert history[-1]["to_stage"] == "Converted" and history[-1]["note"] == "Budget approved"
    assert history[-1]["changed_by_id"] == ASHA  # who converted it is recorded


def test_admin_conversion_keeps_every_existing_rejection(client):
    admin = lambda: login_as(client, ASHA)  # noqa: E731
    lead = new_lead(client)
    before = snapshot()
    no_comment = convert(admin(), lead["id"], note="   ")
    assert no_comment.status_code == 422 and "Enter a conversion comment." in detail(no_comment)
    no_task = admin().post(f"/api/leads/{lead['id']}/convert", json={**DONE, "note": "Budget approved"})
    assert no_task.status_code == 422
    skipped = admin().post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "note": "Ready"})
    assert skipped.status_code == 409 and "Complete Nurturing and Demo" in skipped.json()["detail"]
    assert snapshot() == before  # nothing was created by any refused attempt
    # a closed lead can't be converted, and a converted one can't be converted again
    lost = new_lead(client)
    assert client.post(f"/api/leads/{lost['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Too costly"}).status_code == 200
    assert convert(admin(), lost["id"]).status_code in (400, 409)
    assert convert(admin(), lead["id"]).status_code == 200
    assert convert(admin(), lead["id"]).status_code in (400, 409)
    # the same person at the same company can't get a second open deal with the same name (duplicate check)
    twin = new_lead(client, first_name=lead["first_name"], last_name=lead["last_name"], company=lead["company"],
                    email=f"twin{next(N)}@example.test")
    before = snapshot()
    duplicate = convert(admin(), twin["id"])
    assert duplicate.status_code == 409, duplicate.text
    assert snapshot() == before


def test_manager_and_salesperson_conversion_is_unchanged(client):
    mine = new_lead(client)
    assert convert(client, mine["id"]).status_code == 200  # Ravi, his own lead
    for_team = new_lead(client)
    assert convert(login_as(client, PRIYA), for_team["id"]).status_code == 200  # a Manager, someone else's lead
    other = new_lead(login_as(client, RAVI))
    sam = add_salesperson(client)
    assert convert(login_as(client, sam), other["id"]).status_code == 404  # can't see it
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    assert convert(login_as(client, sam), other["id"]).status_code == 403  # team access is view-only


def test_the_admin_assistant_offers_conversion_and_no_other_sales_action(client):
    admin = Acting(id=ASHA, role="Admin", full_name="Asha Rao", email="asha@crm.test", permissions=frozenset())
    names = {t["function"]["name"] for t in assistant.tools_for(admin)}
    assert "convert_lead" in names and {"crm_report", "get_lead", "search"} <= names
    assert not names & {"create_lead", "update_lead", "move_lead_stage", "mark_lead_lost", "mark_opportunity_won",
                        "move_opportunity_stage", "create_task", "transfer_lead", "delete_lead", "create_opportunity"}
    assert "convert a lead" in assistant.role_guidance(admin)
    for role in ("Manager", "Salesperson"):  # unchanged for the other roles
        me = Acting(id=RAVI, role=role, full_name="X", email="x@crm.test", permissions=frozenset())
        assert {"create_lead", "convert_lead"} <= {t["function"]["name"] for t in assistant.tools_for(me)}


def test_the_admin_converts_through_the_assistant_with_the_same_rules(client, ai):
    script, seen = ai
    lead = new_lead(client)
    login_as(client, ASHA)
    task = {"task_title": TASK["title"], "task_due_date": TASK["due_date"]}
    script += [[call("convert_lead", lead_id=lead["id"], completed_stages=DONE["completed_stages"], note="  ", **task)],
               "What is your conversion comment?"]
    client.post("/api/assistant/chat", json={"message": "Convert it"})
    assert "Enter a conversion comment." in json.loads(seen[-1][-1]["content"])["error"]
    script += [[call("convert_lead", lead_id=lead["id"], completed_stages=DONE["completed_stages"],
                     note="Budget approved", **task)], "Converted."]
    assert client.post("/api/assistant/chat", json={"message": "Budget approved"}).status_code == 200
    assert client.get(f"/api/leads/{lead['id']}").json()["stage"] == "Converted"
    script += [[call("create_lead", **{k: v for k, v in lead_body().items() if k != "welcome_email"})], "I can't."]
    client.post("/api/assistant/chat", json={"message": "Create a lead"})
    assert "isn't available for the Admin role" in json.loads(seen[-1][-1]["content"])["error"]


# ---------- 6. Lead Source and the New Lead rules (API) ----------

@pytest.mark.parametrize("source", SOURCES)
def test_every_lead_source_can_be_saved_and_reopened(client, source):
    extra = {"Other": {"source_detail": "Trade fair 2026"},
             "LinkedIn": {"linkedin_url": "https://www.linkedin.com/in/nia-synthetic"}}.get(source, {})
    lead = new_lead(client, source=source, **extra)
    again = client.get(f"/api/leads/{lead['id']}").json()
    assert again["source"] == source
    assert again["source_detail"] == ("Trade fair 2026" if source == "Other" else None)
    listed = client.get("/api/leads", params={"source": source}).json()  # the Source filter accepts every source
    rows = listed["items"] if isinstance(listed, dict) else listed
    assert lead["id"] in {r["id"] for r in rows}


@pytest.mark.parametrize("url", [None, "", "   "])
def test_linkedin_source_needs_the_profile_url(client, url):
    body = lead_body(source="LinkedIn") | ({} if url is None else {"linkedin_url": url})
    res = client.post("/api/leads", json=body)
    assert res.status_code == 422 and schemas.LINKEDIN_PROFILE_REQUIRED in detail(res)
    saved = new_lead(client, source="LinkedIn", linkedin_url="www.linkedin.com/in/Nia-Synthetic/")
    assert saved["linkedin_url"] == "https://linkedin.com/in/nia-synthetic"  # the one profile field, as before
    for source in ("Website", "Referral", "Event"):  # optional for every other source
        assert new_lead(client, source=source)["linkedin_url"] is None


@pytest.mark.parametrize("given", [None, "", "   ", "\t\n "], ids=["missing", "empty", "spaces", "whitespace"])
def test_other_source_needs_what_it_is(client, given):
    body = lead_body(source="Other") | ({} if given is None else {"source_detail": given})
    res = client.post("/api/leads", json=body)
    assert res.status_code == 422 and schemas.SOURCE_DETAIL_REQUIRED in detail(res)
    no_source = lead_body()
    no_source.pop("source")  # the API's default source is Other: it needs its description too
    assert client.post("/api/leads", json=no_source).status_code == 422


def test_other_source_description_is_kept_bounded_and_cleared_for_other_sources(client):
    lead = new_lead(client, source="Other", source_detail="  Partner webinar, March  ")
    assert lead["source_detail"] == "Partner webinar, March"
    assert client.get(f"/api/leads/{lead['id']}").json()["source_detail"] == "Partner webinar, March"
    too_long = client.post("/api/leads", json=lead_body(source="Other", source_detail="x" * 101))
    assert too_long.status_code == 422
    assert new_lead(client, source="Other", source_detail="x" * 100)["source_detail"] == "x" * 100
    # a description sent with another source isn't kept
    assert new_lead(client, source="Event", source_detail="Ignored")["source_detail"] is None
    # editing: blank is refused; another source clears it; back to Other needs a description again
    url = f"/api/leads/{lead['id']}"
    res = client.put(url, json={"source": "Other", "source_detail": "   "})
    assert res.status_code == 400 and res.json()["detail"] == schemas.SOURCE_DETAIL_REQUIRED
    assert client.put(url, json={"source": "Other", "source_detail": "Partner webinar, April"}).json()["source_detail"] == "Partner webinar, April"
    assert client.put(url, json={"source": "Event", "source_detail": "Partner webinar, April"}).json()["source_detail"] is None
    back = client.put(url, json={"source": "Other"})
    assert back.status_code == 400 and back.json()["detail"] == schemas.SOURCE_DETAIL_REQUIRED
    assert client.get(url).json()["source"] == "Event"  # a refused edit changes nothing


@pytest.mark.parametrize("first", [None, "", "   "], ids=["missing", "empty", "spaces"])
def test_first_name_is_required_on_new_leads(client, first):
    body = lead_body() | ({"first_name": first} if first is not None else {})
    if first is None:
        body.pop("first_name")
    res = client.post("/api/leads", json=body)
    assert res.status_code == 422 and schemas.FIRST_NAME_REQUIRED in detail(res)
    # Last Name keeps its requirement
    no_last = lead_body()
    no_last.pop("last_name")
    assert client.post("/api/leads", json=no_last).status_code == 422
    assert new_lead(client, first_name="  Nia ")["first_name"] == "Nia"


def test_company_links_are_optional_and_checked_when_given(client):
    plain = new_lead(client)
    assert plain["company_website"] is None and plain["company_linkedin_url"] is None
    links = new_lead(client, company_website="followup.example", company_linkedin_url="linkedin.com/company/followup",
                     email=f"nia{next(N)}@followup.example")  # on the website's domain (that check is unchanged)
    assert links["company_website"] == "https://followup.example"
    assert links["company_linkedin_url"] == "https://linkedin.com/company/followup"
    bad_site = client.post("/api/leads", json=lead_body(company_website="not a site"))
    assert bad_site.status_code == 422 and "Enter a valid web address" in detail(bad_site)
    bad_page = client.post("/api/leads", json=lead_body(company_linkedin_url="https://followup.example/about"))
    assert bad_page.status_code == 422 and "Enter a LinkedIn address" in detail(bad_page)
    # clearing them on an edit is allowed
    res = client.put(f"/api/leads/{links['id']}", json={"company_website": None, "company_linkedin_url": ""})
    assert res.status_code == 200 and res.json()["company_website"] is None and res.json()["company_linkedin_url"] is None


# ---------- older leads: viewable, and unrelated edits still save ----------

def full_form(lead: dict, **changes) -> dict:
    """What the Edit Lead form sends: every field, as the lead has it, plus the user's change."""
    keep = ("salutation", "first_name", "last_name", "company", "title", "industry", "email", "phone", "linkedin_url",
            "company_website", "company_linkedin_url", "location", "source", "source_detail")
    return {k: lead.get(k) for k in keep} | changes


def test_older_leads_without_the_new_values_stay_viewable_and_editable(client):
    lead_id = legacy_lead()
    url = f"/api/leads/{lead_id}"
    lead = client.get(url).json()
    assert lead["first_name"] is None and lead["source"] == "Other" and lead["source_detail"] is None
    assert lead_id in {r["id"] for r in client.get("/api/leads").json()}
    # an unrelated edit through the whole form saves; nothing is filled in or changed for the missing values
    res = client.put(url, json=full_form(lead, phone="+1 555 0100", first_name="", source_detail=""))
    assert res.status_code == 200, res.text
    after = res.json()
    assert (after["phone"], after["first_name"], after["source"], after["source_detail"]) == ("+1 555 0100", None, "Other", None)
    # ...and the values can be added later
    assert client.put(url, json={"first_name": "Lea", "source_detail": "Old CRM import"}).status_code == 200
    # once a lead has a first name, an edit can't remove it
    cleared = client.put(url, json={"first_name": "  "})
    assert cleared.status_code == 400 and cleared.json()["detail"] == schemas.FIRST_NAME_REQUIRED
    assert client.get(url).json()["first_name"] == "Lea"


def test_changing_the_source_asks_for_what_the_new_source_needs(client):
    lead_id = legacy_lead(source="Website", first_name="Lea")
    url = f"/api/leads/{lead_id}"
    to_linkedin = client.put(url, json={"source": "LinkedIn"})
    assert to_linkedin.status_code == 400 and to_linkedin.json()["detail"] == schemas.LINKEDIN_PROFILE_REQUIRED
    to_other = client.put(url, json={"source": "Other", "source_detail": ""})
    assert to_other.status_code == 400 and to_other.json()["detail"] == schemas.SOURCE_DETAIL_REQUIRED
    assert client.get(url).json()["source"] == "Website"
    ok = client.put(url, json={"source": "LinkedIn", "linkedin_url": "linkedin.com/in/lea-legacy"})
    assert ok.status_code == 200 and ok.json()["source"] == "LinkedIn"
    removed = client.put(url, json={"linkedin_url": ""})
    assert removed.status_code == 400 and removed.json()["detail"] == schemas.LINKEDIN_PROFILE_REQUIRED
    # an uploaded LinkedIn lead without a profile: other edits still save
    uploaded = legacy_lead(source="LinkedIn", first_name="Uma")
    assert client.put(f"/api/leads/{uploaded}", json={"phone": "+1 555 0101", "linkedin_url": None}).status_code == 200


def test_existing_source_values_are_never_rewritten(client):
    ids = {source: legacy_lead(source=source, first_name="Kai") for source in constants.LEAD_SOURCES}
    for source, lead_id in ids.items():
        res = client.put(f"/api/leads/{lead_id}", json={"title": "Buyer"})
        assert res.status_code == 200, (source, res.text)
        assert res.json()["source"] == source and res.json()["source_detail"] is None


def test_conversion_carries_the_profile_and_works_for_older_leads(client):
    lead = new_lead(client, source="LinkedIn", linkedin_url="linkedin.com/in/nia-convert")
    res = convert(login_as(client, ASHA), lead["id"])
    assert res.status_code == 200 and res.json()["contact"]["linkedin_url"] == "https://linkedin.com/in/nia-convert"
    old = legacy_lead(first_name=None, email=f"legacy{next(N)}@example.test")
    assert convert(login_as(client, RAVI), old).status_code == 200  # a missing first name or description doesn't block it


# ---------- import, export and the AI Assistant ----------

def csv_file(rows, name="followups.csv"):
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return {"file": (name, out.getvalue().encode(), "text/csv")}


def test_upload_keeps_linkedin_and_other_descriptions_without_making_them_up(client):
    rows = [["First Name", "Last Name", "Company", "Email", "Person Linkedin Url", "Lead Source", "Lead Source Details"],
            ["Ana", "Upload1", "Up One", "ana.up1@example.test", "linkedin.com/in/ana-up1", "LinkedIn", ""],
            ["Ben", "Upload2", "Up Two", "ben.up2@example.test", "", "linkedin", ""],
            ["Cy", "Upload3", "Up Three", "cy.up3@example.test", "", "Other", "  Partner list  "],
            ["Di", "Upload4", "Up Four", "di.up4@example.test", "", "Other", ""],
            ["", "Upload5", "Up Five", "eve.up5@example.test", "", "", ""]]
    done = client.post("/api/leads/import", files=csv_file(rows), data={"dry_run": "false"}).json()
    assert done["created"] == 5, done  # uploads keep their own rules: no row is skipped for these
    assert any("Lead Source is LinkedIn but the row has no valid LinkedIn profile URL" in w["reason"] for w in done["warnings"])
    with db_session() as db:
        got = {l.last_name: (l.source, l.source_detail, l.first_name)
               for l in db.scalars(select(Lead).where(Lead.last_name.like("Upload%")))}
    assert got == {"Upload1": ("LinkedIn", None, "Ana"), "Upload2": ("LinkedIn", None, "Ben"),
                   "Upload3": ("Other", "Partner list", "Cy"), "Upload4": ("Other", None, "Di"),
                   "Upload5": ("Upload", None, None)}


def test_download_includes_the_source_details(client):
    new_lead(client, source="Other", source_detail="Partner webinar")
    res = login_as(client, ASHA).get("/api/leads/export", params={"reason": "Source review", "format": "csv"})
    assert res.status_code == 200
    table = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    head = table[0]
    assert head[head.index("Lead Source") + 1] == "Lead Source Details"
    assert any(r[head.index("Lead Source")] == "Other" and r[head.index("Lead Source Details")] == "Partner webinar"
               for r in table[1:])


def test_assistant_create_lead_asks_for_what_the_new_lead_needs(client, ai):
    script, seen = ai
    base = {"last_name": "Assist", "company": "Assisted Co", "email": "assist@example.test"}

    def error_for(**args):
        script.extend([[call("create_lead", **args)], "Please tell me more."])
        client.post("/api/assistant/chat", json={"message": "Create a lead"})
        return json.loads(seen[-1][-1]["content"]).get("error", "")

    assert "First Name" in error_for(**base, source="Website")
    assert "Lead Source" in error_for(**base, first_name="Ada")
    assert "Specify lead source" in error_for(**base, first_name="Ada", source="Other")
    assert "LinkedIn Profile URL" in error_for(**base, first_name="Ada", source="LinkedIn")
    assert "Company Website" not in error_for(**base, first_name="Ada", source="Other")  # optional now
    script.extend([[call("create_lead", **base, first_name="Ada", source="Other", source_detail="Conference")], "Done."])
    client.post("/api/assistant/chat", json={"message": "Create it, source Other: Conference"})
    with db_session() as db:
        lead = db.scalars(select(Lead).where(Lead.email == "assist@example.test")).one()
        assert (lead.first_name, lead.source, lead.source_detail) == ("Ada", "Other", "Conference")
        assert lead.company_website is None and lead.company_linkedin_url is None
    tool = next(t["function"] for t in assistant.TOOLS if t["function"]["name"] == "create_lead")
    assert tool["parameters"]["properties"]["source"]["enum"] == SOURCES
    assert "source_detail" in tool["parameters"]["properties"]
    assert set(tool["parameters"]["required"]) == {"first_name", "last_name", "company", "email", "source"}


# ---------- the database: new installs (schema.sql) and the startup upgrade (existing databases) ----------

def test_sources_and_the_description_column_agree_everywhere():
    assert list(get_args(schemas.LeadSource)) == constants.LEAD_SOURCES
    assert "LinkedIn" in constants.LEAD_SOURCES and constants.LEAD_SOURCE_DETAIL_MAX == schemas.SOURCE_DETAIL_MAX == 100
    sql = (Path(__file__).resolve().parents[2] / "database" / "schema.sql").read_text(encoding="utf-8")
    allowed = re.search(r"source\s+VARCHAR\(20\) NOT NULL DEFAULT 'Other'\s*CHECK \(source IN \(([^)]*)\)\)", sql).group(1)
    assert [s.strip(" '") for s in allowed.split(",")] == constants.LEAD_SOURCES
    assert re.search(r"^\s*source_detail VARCHAR\(100\),", sql, re.M)
    assert models.Lead.__table__.c.source_detail.type.length == 100 and models.Lead.__table__.c.source_detail.nullable
    upgrade = inspect.getsource(main.upgrade_database)
    assert '("leads", "source_detail", "VARCHAR(100)")' in upgrade  # ADD COLUMN IF NOT EXISTS: additive, repeatable
    assert 'sources = ",".join(f"\'{s}\'" for s in LEAD_SOURCES)' in upgrade
    assert "leads_source_check CHECK (source IN ({sources}))" in upgrade
    # the upgrade only widens the allowed list and adds an empty column: it doesn't update leads' sources or details
    assert "SET source_detail" not in upgrade and "SET source = 'LinkedIn'" not in upgrade


def test_filling_in_created_by_keeps_every_leads_last_modified():
    """The one-off created_by_id backfill for older leads runs with the leads updated_at trigger off, inside the same
    transaction, and only when a lead is missing it: the upgrade never resets Last Modified."""
    upgrade = inspect.getsource(main.upgrade_database)
    off = upgrade.index("ALTER TABLE leads DISABLE TRIGGER trg_leads_updated_at")
    backfill = upgrade.index("UPDATE leads l SET created_by_id")
    on = upgrade.index("ALTER TABLE leads ENABLE TRIGGER trg_leads_updated_at")
    assert upgrade.index("SELECT EXISTS (SELECT 1 FROM leads WHERE created_by_id IS NULL)") < off < backfill < on
    assert "with engine.begin() as conn:" in upgrade  # one transaction: if the UPDATE fails, the trigger stays on
    assert "SET updated_at" not in upgrade
