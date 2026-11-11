"""PowerPoint (.pptx) and Excel (.xlsx) files on opportunities: checked by content like Word files, downloaded (no
preview), accepted in the Change Stage and Mark as Won popups, and addable to a Won deal (with its stage and uploader)
while deleting stays limited to open deals. All files are made up here; nothing is sent."""
import io
import itertools
import json
import zipfile

import pytest
from sqlalchemy import func, select

from app import mailer
from app.database import get_db
from app.main import app
from app.models import OpportunityAttachment
from app.routers.attachments import MAX_FILE_BYTES
from conftest import login_as

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin (conftest.py)
TASK = {"title": "Synthetic next step", "due_date": "2030-01-15T10:00:00"}
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NAMES = itertools.count(1)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)


def package(main_path: str, main_type: str, rel_target: str | None = None) -> bytes:
    """A minimal Office Open XML package: [Content_Types].xml, _rels/.rels and the main part."""
    types = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             f'<Override PartName="/{main_path}" ContentType="{main_type}"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            f' Target="{rel_target or main_path}"/></Relationships>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr(main_path, "<synthetic/>")
    return buffer.getvalue()


PPTX = package("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")
XLSX = package("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
XLSM = package("xl/workbook.xml", "application/vnd.ms-excel.sheet.macroEnabled.main+xml")          # macro-enabled
POTX = package("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml")
PPSX = package("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml")
POINTS_ELSEWHERE = package("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                           rel_target="xl/other.xml")                                                  # broken package
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504                                            # old .ppt / .xls
PLAIN_ZIP = (lambda b: (zipfile.ZipFile(b, "w").writestr("notes.txt", "hello"), b.getvalue())[1])(io.BytesIO())
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def db():
    return next(app.dependency_overrides[get_db]())


def file_rows() -> int:
    with db() as s:
        return s.scalar(select(func.count()).select_from(OpportunityAttachment))


def new_opportunity(client, owner=RAVI) -> dict:
    login_as(client, owner)
    n = next(NAMES)
    lead = client.post("/api/leads", json={"first_name": "Test", "last_name": f"Buyer{n}", "company": f"Office Co {n}",
                                           "email": f"office{n}@example.test", "welcome_email": False}).json()
    res = client.post(f"/api/leads/{lead['id']}/convert", json={"task": TASK, "completed_stages": ["New", "Nurturing", "Demo"],
                                                                 "expected_value": 1000, "note": "Synthetic conversion"})
    assert res.status_code == 200, res.text
    return res.json()["opportunity"]


def finish_stage_tasks(client, opp_id):
    for t in client.get(f"/api/opportunities/{opp_id}").json()["tasks"]:
        if t["status"] == "Open" and not t["is_date_reminder"]:
            assert client.put(f"/api/tasks/{t['id']}/complete").status_code == 200


def to_proposal(client, opp_id):
    finish_stage_tasks(client, opp_id)
    res = client.put(f"/api/opportunities/{opp_id}/stage", json={"stage": "Proposal", "note": "Synthetic", "task": TASK,
                                                                  "completed_stages": ["Discovery"]})
    assert res.status_code == 200, res.text


def to_won(client, opp_id):
    finish_stage_tasks(client, opp_id)
    res = client.post(f"/api/opportunities/{opp_id}/won", json={"note": "Synthetic win", "task": TASK, "final_value": 900,
                                                                 "completed_stages": ["Discovery", "Proposal"]})
    assert res.status_code == 200, res.text


def upload(client, opp_id, name, data):
    return client.post(f"/api/opportunities/{opp_id}/attachments", files={"file": (name, data, "application/octet-stream")})


# ---------- accepted and downloaded ----------

def test_powerpoint_and_excel_files_are_saved_with_the_detected_type_and_downloaded(client):
    opp = new_opportunity(client)
    deck = upload(client, opp["id"], "Synthetic Proposal.pptx", PPTX)
    sheet = upload(client, opp["id"], "Synthetic Pricing.XLSX", XLSX)
    assert deck.status_code == 201 and sheet.status_code == 201, (deck.text, sheet.text)
    assert (deck.json()["content_type"], deck.json()["stage"], deck.json()["uploaded_by_name"]) == \
        (PPTX_TYPE, "Opportunity", "Ravi Kumar")
    assert sheet.json()["content_type"] == XLSX_TYPE
    for item, data, kind in ((deck.json(), PPTX, PPTX_TYPE), (sheet.json(), XLSX, XLSX_TYPE)):
        # no preview: always a download, through the logged-in file request
        for query in ("", "?download=true"):
            res = client.get(f"/api/opportunities/{opp['id']}/attachments/{item['id']}/file{query}")
            assert res.status_code == 200 and res.content == data
            assert res.headers["content-type"] == kind
            assert res.headers["content-disposition"].startswith("attachment;")
            assert res.headers["x-content-type-options"] == "nosniff" and "no-store" in res.headers["cache-control"]
    token = client.headers.pop("Authorization").split(" ", 1)[1]
    assert client.get(f"/api/opportunities/{opp['id']}/attachments/{deck.json()['id']}/file?token={token}").status_code == 401


# ---------- refused, with a clear reason, and nothing saved ----------

@pytest.mark.parametrize("name, data, status, message", [
    ("Old deck.ppt", OLE, 415, "Old deck.ppt: old PowerPoint files (.ppt) can't be uploaded. Open it in PowerPoint, save it as .pptx"),
    ("Old sheet.xls", OLE, 415, "Old sheet.xls: old Excel files (.xls) can't be uploaded. Open it in Excel, save it as .xlsx"),
    ("Locked.pptx", OLE, 415, "Locked.pptx is an old-format or password-protected PowerPoint file. Save it as a regular .pptx"),
    ("Locked.xlsx", OLE, 415, "Locked.xlsx is an old-format or password-protected Excel file. Save it as a regular .xlsx"),
    ("Macro.xlsx", XLSM, 415, "Macro.xlsx isn't an Excel workbook (.xlsx). Only regular Excel workbooks can be uploaded, not macro-enabled"),
    ("Template.pptx", POTX, 415, "Template.pptx isn't a PowerPoint presentation (.pptx). Only regular PowerPoint presentations"),
    ("Show.pptx", PPSX, 415, "Show.pptx isn't a PowerPoint presentation (.pptx)"),
    ("Book.xlsm", XLSM, 415, "Book.xlsm: only PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), JPG and PNG files can be uploaded."),
    ("Deck.xlsx", PPTX, 415, "Deck.xlsx is named as an Excel workbook (.xlsx) but is really a PowerPoint presentation (.pptx)"),
    ("Sheet.pptx", XLSX, 415, "Sheet.pptx is named as a PowerPoint presentation (.pptx) but is really an Excel workbook (.xlsx)"),
    ("Report.docx", PPTX, 415, "Report.docx is named as a Word document (.docx) but is really a PowerPoint presentation (.pptx)"),
    ("Deck.pptx", PDF, 415, "Deck.pptx is named as a PowerPoint presentation (.pptx) but is really a PDF"),
    ("Notes.xlsx", PLAIN_ZIP, 415, "Notes.xlsx isn't an Excel workbook (.xlsx)"),
    ("Broken.xlsx", POINTS_ELSEWHERE, 415, "Broken.xlsx isn't an Excel workbook (.xlsx)"),
    ("Cut off.pptx", PPTX[: len(PPTX) // 2], 422, "Cut off.pptx looks damaged, so it can't be uploaded."),
    ("Empty.xlsx", b"", 422, "Empty.xlsx is empty."),
    ("Text.xlsx", b"Name,Price\nSynthetic,1\n", 415, "Text.xlsx isn't a real Excel workbook (.xlsx)"),
])
def test_unsupported_damaged_and_mismatched_office_files_are_refused(client, name, data, status, message):
    opp = new_opportunity(client)
    before = file_rows()
    res = upload(client, opp["id"], name, data)
    assert res.status_code == status, res.text
    assert res.json()["detail"].startswith(message), res.json()["detail"]
    assert file_rows() == before


def test_office_files_over_20_mb_are_refused(client):
    opp = new_opportunity(client)
    big = PPTX + b"\0" * (MAX_FILE_BYTES + 1 - len(PPTX))
    res = upload(client, opp["id"], "Big deck.pptx", big)
    assert res.status_code == 413 and "larger than 20 MB" in res.json()["detail"]
    assert file_rows() == 0


# ---------- the Change Stage and Mark as Won popups (files saved with the change, all or nothing) ----------

def test_popups_take_powerpoint_and_excel_and_refuse_the_whole_save_for_one_bad_file(client):
    opp = new_opportunity(client)
    finish_stage_tasks(client, opp["id"])
    form = {"stage": "Proposal", "note": "Synthetic", "task": json.dumps(TASK), "completed_stages": ["Discovery"]}
    bad = client.post(f"/api/opportunities/{opp['id']}/stage-with-files", data=form, files=[
        ("files", ("Deck.pptx", io.BytesIO(PPTX), "application/octet-stream")),
        ("files", ("Old.xls", io.BytesIO(OLE), "application/octet-stream"))])
    assert bad.status_code == 415 and "old Excel files (.xls)" in bad.json()["detail"]
    assert client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity" and file_rows() == 0
    good = client.post(f"/api/opportunities/{opp['id']}/stage-with-files", data=form, files=[
        ("files", ("Deck.pptx", io.BytesIO(PPTX), "application/octet-stream")),
        ("files", ("Pricing.xlsx", io.BytesIO(XLSX), "application/octet-stream"))])
    assert good.status_code == 200, good.text
    files = {f["filename"]: f for f in client.get(f"/api/opportunities/{opp['id']}/attachments").json()}
    assert {(n, f["stage"], f["content_type"]) for n, f in files.items()} == {
        ("Deck.pptx", "Proposal", PPTX_TYPE), ("Pricing.xlsx", "Proposal", XLSX_TYPE)}
    # Mark as Won with an Excel file: labelled Proposal, the stage being closed
    finish_stage_tasks(client, opp["id"])
    res = client.post(f"/api/opportunities/{opp['id']}/won-with-files", data={
        "note": "Synthetic win", "task": json.dumps(TASK), "final_value": "900"},
        files=[("files", ("Final pricing.xlsx", io.BytesIO(XLSX), "application/octet-stream"))])
    assert res.status_code == 200 and res.json()["stage"] == "Won"
    signed = next(f for f in client.get(f"/api/opportunities/{opp['id']}/attachments").json()
                  if f["filename"] == "Final pricing.xlsx")
    assert (signed["stage"], signed["content_type"], signed["uploaded_by_name"]) == ("Proposal", XLSX_TYPE, "Ravi Kumar")


def test_popups_still_take_at_most_five_files(client):
    opp = new_opportunity(client)
    finish_stage_tasks(client, opp["id"])
    form = {"stage": "Proposal", "note": "Synthetic", "task": json.dumps(TASK), "completed_stages": ["Discovery"]}
    res = client.post(f"/api/opportunities/{opp['id']}/stage-with-files", data=form, files=[
        ("files", (f"Deck {i}.pptx", io.BytesIO(PPTX), "application/octet-stream")) for i in range(6)])
    assert res.status_code in (400, 413, 422), res.text
    assert file_rows() == 0 and client.get(f"/api/opportunities/{opp['id']}").json()["stage"] == "Opportunity"


# ---------- an already Won deal ----------

def test_files_can_be_added_to_a_won_deal_with_its_stage_and_uploader_but_not_deleted(client):
    opp = new_opportunity(client)
    to_won(client, opp["id"])
    mine = upload(login_as(client, RAVI), opp["id"], "Signed order.pptx", PPTX)
    assert mine.status_code == 201, mine.text
    assert (mine.json()["stage"], mine.json()["uploaded_by_id"], mine.json()["uploaded_by_name"]) == ("Won", RAVI, "Ravi Kumar")
    managers = upload(login_as(client, PRIYA), opp["id"], "Final pricing.xlsx", XLSX)
    assert managers.status_code == 201 and managers.json()["stage"] == "Won"
    assert managers.json()["uploaded_by_name"] == "Priya Sharma"
    names = [f["filename"] for f in client.get(f"/api/opportunities/{opp['id']}/attachments").json()]
    assert set(names) == {"Signed order.pptx", "Final pricing.xlsx"}
    # closed deals keep their files: no delete, for the uploader, a Manager or the Admin
    for who in (RAVI, PRIYA, ASHA):
        res = login_as(client, who).delete(f"/api/opportunities/{opp['id']}/attachments/{mine.json()['id']}")
        assert res.status_code == 409 and "can't be deleted any more" in res.json()["detail"]


def test_won_uploads_need_edit_rights_and_lost_deals_take_no_files(client):
    opp = new_opportunity(client)
    to_won(client, opp["id"])
    sam = login_as(client, ASHA).post("/api/users", json={"full_name": "Sam Tester", "email": "sam@crm.test",
                                                           "password": "Password123", "role": "Salesperson"}).json()["id"]
    assert upload(login_as(client, sam), opp["id"], "Mine.pptx", PPTX).status_code == 404  # can't see the deal
    assert login_as(client, PRIYA).put(f"/api/users/{sam}/team-access", json={"team_access": True}).status_code == 200
    res = upload(login_as(client, sam), opp["id"], "Mine.pptx", PPTX)  # read-only team access
    assert res.status_code == 403
    lost = new_opportunity(client)
    res = login_as(client, RAVI).post(f"/api/opportunities/{lost['id']}/lost", json={"lost_reason": "Price",
                                                                                   "lost_notes": "Synthetic"})
    assert res.status_code == 200
    res = upload(client, lost["id"], "Late.xlsx", XLSX)
    assert res.status_code == 409 and "This opportunity is Lost, so files can't be added any more" in res.json()["detail"]
    assert file_rows() == 0


# ---------- the API description says the same as the app ----------

def test_api_descriptions_list_powerpoint_and_excel(client):
    spec = client.get("/openapi.json").json()["paths"]
    upload_form = spec["/api/opportunities/{opportunity_id}/attachments"]["post"]["requestBody"]
    stage_form = spec["/api/opportunities/{opportunity_id}/stage-with-files"]["post"]["requestBody"]
    won_form = spec["/api/opportunities/{opportunity_id}/won-with-files"]["post"]["requestBody"]
    for form, field in ((upload_form, "file"), (stage_form, "files"), (won_form, "files")):
        text = form["content"]["multipart/form-data"]["schema"]["properties"][field]["description"]
        assert "PowerPoint (.pptx), Excel (.xlsx)" in text and "20 MB" in text, text


# ---------- PostgreSQL keeps the same rules (the test database is SQLite, without these CHECK constraints) ----------

def test_the_postgresql_rules_allow_every_accepted_type_and_stage():
    """database/schema.sql (new databases) and the startup upgrade in main.py (existing ones) must allow every file type
    the upload accepts and every stage a file can be added at, or a valid PowerPoint / Excel / Won upload fails there."""
    import inspect
    import re
    from pathlib import Path

    from app import main
    from app.routers.attachments import TYPE_OF_EXTENSION, UPLOAD_STAGES

    schema = Path(__file__).resolve().parents[2].joinpath("database", "schema.sql").read_text(encoding="utf-8")
    table = schema[schema.index("CREATE TABLE opportunity_attachments"):]
    table = table[:table.index(");")]
    types = set(re.findall(r"'([a-z]+/[^']+)'", table[table.index("content_type"):]))
    stages = set(re.findall(r"'([A-Za-z]+)'", table[table.index("stage"):table.index("filename")]))
    assert types == set(TYPE_OF_EXTENSION.values())
    assert stages == set(UPLOAD_STAGES) == {"Opportunity", "Discovery", "Proposal", "Won"}
    upgrade = inspect.getsource(main.upgrade_database)
    assert "opportunity_attachments_content_type_check" in upgrade and "attachments.TYPE_OF_EXTENSION.values()" in upgrade
    assert '("opportunity_attachments", "stage", attachments.UPLOAD_STAGES)' in upgrade
