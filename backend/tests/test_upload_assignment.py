"""Bulk upload: unique emails, the company-domain rule, and who owns the uploaded leads (one person, the file's
Lead Owner column, or shared evenly), like Salesforce's Data Import Wizard. All data is made up."""
import csv
import io

from tests.conftest import login_as

HEADER = ["First Name", "Last Name", "Company", "Email", "Website", "Lead Owner"]


def upload(client, rows, dry_run=False, **form):
    out = io.StringIO()
    csv.writer(out).writerows([HEADER, *rows])
    data = {"dry_run": str(dry_run).lower(), **{k: v for k, v in form.items() if k not in ("owner_ids", "counts")}}
    if "owner_ids" in form:
        data["owner_ids"] = [str(i) for i in form["owner_ids"]]
    if "counts" in form:
        data["counts"] = form["counts"]
    return client.post("/api/leads/import", files={"file": ("team.csv", out.getvalue().encode(), "text/csv")}, data=data)


def add_salesperson(client, name, email):
    res = login_as(client, 3).post("/api/users", json={"full_name": name, "email": email, "password": "Start2026",
                                                       "role": "Salesperson"})
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


def owners_of(client, *last_names):
    items = login_as(client, 1).get("/api/leads/page", params={"view": "all", "limit": 500}).json()["items"]
    return {l["last_name"]: l["owner_id"] for l in items if l["last_name"] in last_names}


def rows(n, prefix="Row", owner=""):
    return [["A", f"{prefix}{i}", "Acme", f"{prefix.lower()}{i}@acme-example.com", "acme-example.com", owner]
            for i in range(n)]


def test_email_on_another_domain_is_kept_with_a_note(client):
    res = upload(client, [["Asha", "Iyer", "Acme", "asha@acme-group.example", "acme-example.com", ""],
                          ["Ben", "Cole", "Acme", "ben@acme-example.com", "https://www.acme-example.com", ""]])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 2 and body["with_blanks"] == 1
    assert "on another domain than the company website (acme-example.com)" in body["warnings"][0]["reason"]
    # uploaded leads are in the Unassigned Pool; the Manager sees their details there
    emails = {l["last_name"]: l["email"] for l in login_as(client, 1).get(
        "/api/leads/page", params={"view": "unassigned"}).json()["items"]}
    assert emails == {"Iyer": "asha@acme-group.example", "Cole": "ben@acme-example.com"}


def test_emails_already_in_the_crm_are_skipped_whatever_the_stage(client):
    lead = client.post("/api/leads", json={"first_name": "Test", "source": "Website", "last_name": "Old", "company": "Acme", "email": "old@acme-example.com"}).json()
    client.post(f"/api/leads/{lead['id']}/lost", json={"lost_reason": "Price", "lost_notes": "Synthetic"})
    res = upload(client, [["A", "Again", "Acme", "OLD@acme-example.com", "acme-example.com", ""],
                          ["B", "Fresh", "Acme", "fresh@acme-example.com", "acme-example.com", ""],
                          ["C", "Twice", "Acme", "fresh@acme-example.com", "acme-example.com", ""]], dry_run=True)
    body = res.json()
    assert (body["ready"], body["duplicates"]) == (1, 2)
    assert "old@acme-example.com is already in the CRM" in body["errors"][0]["reason"]


def test_uploads_go_to_the_unassigned_pool_whatever_owner_is_sent(client):
    """Every uploaded lead starts with no owner (the Unassigned Pool), whoever uploads it. An owner sent with the
    upload (the old one / even / counts choices) is not used: the result says so, and the uploader is Created By."""
    tara = add_salesperson(client, "Tara Nair", "tara@crm.test")
    ravi = login_as(client, 2)
    for form in ({}, {"owner_id": "1"}, {"assign": "even", "owner_ids": [2, tara]},
                 {"assign": "counts", "counts": [f"{tara}:1"]}, {"owner_id": "3"}):
        res = upload(ravi, rows(2), dry_run=True, **form)
        assert res.status_code == 200, (form, res.text)
        body = res.json()
        assert (body["owner"], body["owners"], body["pool"]) == ("Unassigned Pool", [], True)
        assert all(p["owner_name"] == "Unassigned Pool" for p in body["preview"])
        assert "Unassigned Pool" in body["assign_note"]
        assert ("owner chosen for this upload was not used" in body["assign_note"]) == bool(form)
    done = upload(ravi, rows(3), owner_id=str(tara), assign="one").json()
    assert done["created"] == 3
    got = owners_of(client, "Row0", "Row1", "Row2")
    assert got == {"Row0": None, "Row1": None, "Row2": None}
    items = login_as(client, 1).get("/api/leads/page", params={"view": "unassigned"}).json()["items"]
    assert {(l["created_by_id"], l["owner_name"], l["in_pool"]) for l in items} == {(2, None, True)}
    # nobody is told leads were assigned to them (none were)
    for user in (tara, 1, 2):
        bell = login_as(client, user).get("/api/notifications").json()
        assert not any(n["title"] in ("Leads assigned to you", "Leads created for your team") for n in bell)


def test_a_lead_owner_column_is_not_used(client):
    tara = add_salesperson(client, "Tara Nair", "tara@crm.test")
    data = [["A", "ByEmail", "Acme", "byemail@acme-example.com", "acme-example.com", "TARA@crm.test"],
            ["A", "ByName", "Acme", "byname@acme-example.com", "acme-example.com", "ravi kumar"],
            ["A", "Blank", "Acme", "blank@acme-example.com", "acme-example.com", ""]]
    res = upload(login_as(client, 3), data, assign="column", owner_id=str(tara))  # the Admin: the same pool
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 3 and body["owner"] == "Unassigned Pool"
    assert "Lead Owner" in body["columns_ignored"] and "Lead Owner" not in body["columns_used"]
    assert '"Lead Owner" column was not used' in body["assign_note"]
    assert body["owner_ignored"].startswith("The file's \"Lead Owner\" column was not used")
    assert not any("Owner" in w["reason"] for w in body["warnings"])
    assert owners_of(client, "ByEmail", "ByName", "Blank") == {"ByEmail": None, "ByName": None, "Blank": None}
    # an upload without that column still works (it was required for the old "column" choice)
    out = io.StringIO()
    csv.writer(out).writerows([["Last Name", "Company"], ["NoOwner", "Acme"]])
    res = login_as(client, 1).post("/api/leads/import", data={"assign": "column", "dry_run": "true"},
                                   files={"file": ("x.csv", out.getvalue().encode(), "text/csv")})
    assert res.status_code == 200 and res.json()["ready"] == 1


def test_skipped_rows_are_listed_with_name_company_and_email(client):
    client.post("/api/leads", json={"first_name": "Test", "source": "Website", "last_name": "Old", "company": "Acme", "email": "old@acme-example.com",
                                    "company_website": "acme-example.com"})
    body = upload(client, [["Asha", "Iyer", "Acme", "OLD@acme-example.com", "acme-example.com", ""],
                           ["", "", "Acme", "ben@acme-example.com", "acme-example.com", ""],  # no name at all
                           ["Cara", "Lee", "Acme", "cara@gmail.com", "acme-example.com", ""]], dry_run=True).json()
    assert body["errors"] == [
        {"row": 2, "type": "Duplicate", "reason": "Email old@acme-example.com is already in the CRM (duplicate)",
         "name": "Asha Iyer", "company": "Acme", "email": "OLD@acme-example.com"},
        {"row": 3, "type": "Invalid", "reason": "Name is missing (a first or last name)", "name": "", "company": "Acme",
         "email": "ben@acme-example.com"}]  # a first name alone is enough now (test_optional_fields_and_region.py)
    note = body["warnings"][0]
    assert (note["row"], note["type"], note["name"], note["email"]) == (4, "Changed", "Cara Lee", "cara@gmail.com")
    assert note["reason"].startswith("Left blank: email 'cara@gmail.com' isn't on the company's domain")
