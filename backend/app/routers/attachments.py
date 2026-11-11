"""Files kept on an opportunity: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), JPEG and PNG, up to 20 MB each,
stored in the database.

- Upload: one file per request, while the deal is open (Opportunity, Discovery or Proposal) or Won (a signed order or
  final pricing added after the win). The server checks what the file really is (its content, not the browser's file
  type) and saves the stage the deal is at and who uploaded it.
- Files keep their stage when the deal moves on. Won and Lost files can be viewed and downloaded; no file can be deleted
  after Won / Lost, and none added after Lost.
- PowerPoint and Excel files are downloaded (opened with PowerPoint / Excel on the computer); there is no preview.
  Old .ppt / .xls / .doc files are refused with a request to save them as .pptx / .xlsx / .docx.
- Viewing and downloading need access to the opportunity; uploading needs edit access. Deleting also needs to be
  the person who uploaded the file, or a Manager / Admin.
- Delete only hides the file (deleted_at / deleted_by_id) and adds a line to the Admin's Activity Log.
- Only the Authorization header is accepted here (not ?token=...), so a file address never works on its own.
  The app fetches the file and shows it from a temporary blob: address.
"""
import io
import os
import re
import unicodedata
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, undefer
from starlette.datastructures import UploadFile

from app import schemas
from app.constants import OPPORTUNITY_OPEN_STAGES
from app.database import get_db
from app.models import Opportunity, OpportunityAttachment
from app.security import require_edit, require_view
from app.services import get_or_404, log_activity, now

MAX_FILE_BYTES = 20 * 1024 * 1024               # 20 MiB per file (the app says "20 MB per file")
MAX_REQUEST_BYTES = MAX_FILE_BYTES + 64 * 1024  # the file plus the multipart form around it
READ_CHUNK = 1024 * 1024

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JPEG = "image/jpeg"
PNG = "image/png"
ZIP = "application/zip"                # only used in error messages
OLE = "application/x-ole-storage"      # old .doc files and password-protected Office files
TYPE_OF_EXTENSION = {".pdf": PDF, ".docx": DOCX, ".pptx": PPTX, ".xlsx": XLSX, ".jpg": JPEG, ".jpeg": JPEG,
                     ".png": PNG}
TYPE_NAME = {PDF: "PDF", DOCX: "Word document (.docx)", PPTX: "PowerPoint presentation (.pptx)",
             XLSX: "Excel workbook (.xlsx)", JPEG: "JPEG image", PNG: "PNG image",
             ZIP: "ZIP archive", OLE: "legacy (old-format or password-protected) Office file"}
SUPPORTED = "PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), JPG and PNG files"
PREVIEW_TYPES = {PDF, JPEG, PNG}  # shown in the browser; Word, PowerPoint and Excel files are downloaded
# Old binary Office formats: the program to open them in and the format to save them as
LEGACY_OFFICE = {".doc": ("Word", ".docx"), ".ppt": ("PowerPoint", ".pptx"), ".xls": ("Excel", ".xlsx")}
OFFICE_APP = {DOCX: ("Word", "Word documents"), PPTX: ("PowerPoint", "PowerPoint presentations"),
              XLSX: ("Excel", "Excel workbooks")}

# .docx, .pptx and .xlsx files are zip "packages" (Office Open XML). Only the table of contents and two small XML parts
# are read (never extracted): [Content_Types].xml must declare the main part of a regular document, presentation or
# workbook, and _rels/.rels must point to it. Macro-enabled files, templates and slide shows declare other main parts.
DOCX_MAX_PARTS = 5000
DOCX_MAX_XML_BYTES = 256 * 1024
OFFICE_MAIN_PART = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": DOCX,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": PPTX,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": XLSX,
}
CONTENT_TYPES_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
RELATIONSHIPS_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def header_login_only(request: Request) -> None:
    """Files are only sent to the logged-in app (Authorization: Bearer), never to a link with ?token=..."""
    if not request.headers.get("authorization", "").lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in again", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/api/opportunities", tags=["Opportunity attachments"],
                   dependencies=[Depends(header_login_only)])

# Shown in the API docs (the upload reads the form itself, so the size can be checked before the file is read)
UPLOAD_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["file"],
    "properties": {"file": {"type": "string", "format": "binary",
                            "description": "One PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), JPG or PNG "
                                           "file, up to 20 MB"}}}}}}}


# ---------- file checks ----------

def clean_filename(name: str | None) -> str:
    """The name shown in the app: no folder parts, no control or text-direction characters, at most 255
    characters (the extension is kept)."""
    # form encoding sends " as %22 and line breaks / control characters as %0A, %0D, %09...: undo that first
    name = re.sub(r"%(?:22|[01][0-9A-Fa-f])", lambda m: '"' if m.group() == "%22" else " ", name or "")
    name = unicodedata.normalize("NFC", name).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(" " if ch.isspace() else ch for ch in name if ch.isspace() or not unicodedata.category(ch).startswith("C"))
    name = " ".join(name.split()).strip(" .")
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[: 255 - len(ext)].rstrip(" .") + ext if len(ext) <= 10 else name[:255]
    return name


def first_bytes_type(data: bytes) -> str | None:
    """What the file is, from its first bytes."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"PK\x03\x04"):
        return ZIP
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return OLE
    return None


def damaged(kind: str, data: bytes) -> bool:
    """Basic structure checks: the end of the file must be there (cut-off uploads are refused)."""
    if kind == PDF:
        return b"%%EOF" not in data[-1024:]
    if kind == PNG:
        return data[12:16] != b"IHDR" or b"IEND" not in data[-64:]
    if kind == JPEG:
        return data.rfind(b"\xff\xd9") < 3  # end-of-image marker
    return False


def small_part(package: zipfile.ZipFile, name: str) -> bytes | None:
    """One small part of the zip, read with a size cap; None if it is too big or encrypted."""
    info = package.getinfo(name)
    if info.file_size > DOCX_MAX_XML_BYTES or info.flag_bits & 0x1:
        return None
    with package.open(info) as part:
        content = part.read(DOCX_MAX_XML_BYTES + 1)
    return content if len(content) <= DOCX_MAX_XML_BYTES else None


def xml_root(content: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in content.upper():  # Office files never have one; refusing it also rules out entity tricks
        raise ValueError("DOCTYPE in package part")
    return ElementTree.fromstring(content)


def office_package(data: bytes) -> str:
    """What an Office Open XML (zip) file is: DOCX, PPTX or XLSX for a regular Word document, PowerPoint presentation or
    Excel workbook; "damaged" for a broken package; "other" for any other zip (macro-enabled files, templates, slide
    shows, plain zip archives). The package's [Content_Types].xml must declare the main part, _rels/.rels must point to
    it, and the part must exist. Reads the zip's table of contents and these two small parts only, with size caps."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            parts = package.infolist()
            if len(parts) > DOCX_MAX_PARTS:
                return "damaged"
            names = {p.filename for p in parts}
            if not {"[Content_Types].xml", "_rels/.rels"} <= names:
                return "other"
            types, rels = small_part(package, "[Content_Types].xml"), small_part(package, "_rels/.rels")
            if types is None or rels is None:
                return "damaged"
            main_parts = {o.get("PartName", "").lstrip("/"): OFFICE_MAIN_PART[o.get("ContentType")]
                          for o in xml_root(types).iter(f"{CONTENT_TYPES_NS}Override")
                          if o.get("ContentType") in OFFICE_MAIN_PART}
            targets = {r.get("Target", "").lstrip("/") for r in xml_root(rels).iter(f"{RELATIONSHIPS_NS}Relationship")
                       if r.get("Type", "").endswith("/officeDocument")}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ElementTree.ParseError, KeyError, EOFError, OSError,
            ValueError, RuntimeError, NotImplementedError, zlib.error):
        return "damaged"
    kinds = {kind for part, kind in main_parts.items() if part in targets and part in names}
    return kinds.pop() if len(kinds) == 1 else "other"


def a_or_an(name: str) -> str:
    return f"an {name}" if name[:1].lower() in "aeiou" else f"a {name}"


def checked_type(filename: str, data: bytes) -> str:
    """The file type saved for the file. Refuses (415 / 422) anything that is not a real PDF, .docx, .pptx, .xlsx,
    JPEG or PNG, or whose content does not match its extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in LEGACY_OFFICE:
        program, new_ext = LEGACY_OFFICE[ext]
        raise HTTPException(status_code=415, detail=f"{filename}: old {program} files ({ext}) can't be uploaded. "
                                                    f"Open it in {program}, save it as {new_ext} and upload that.")
    expected = TYPE_OF_EXTENSION.get(ext)
    if expected is None:
        raise HTTPException(status_code=415, detail=f"{filename}: only {SUPPORTED} can be uploaded.")
    if not data:
        raise HTTPException(status_code=422, detail=f"{filename} is empty.")
    actual = first_bytes_type(data)
    if actual == ZIP:
        package = office_package(data)
        if package in OFFICE_APP:
            actual = package
        elif expected in OFFICE_APP:
            raise HTTPException(status_code=422 if package == "damaged" else 415, detail=(
                f"{filename} looks damaged, so it can't be uploaded." if package == "damaged" else
                f"{filename} isn't {a_or_an(TYPE_NAME[expected])}. Only regular {OFFICE_APP[expected][1]} can be "
                "uploaded, not macro-enabled files, templates or other zip files."))
    if actual == OLE and expected in OFFICE_APP:
        program = OFFICE_APP[expected][0]
        raise HTTPException(status_code=415, detail=f"{filename} is an old-format or password-protected {program} "
                                                    f"file. Save it as a regular {ext} without a password and try again.")
    if actual is None:
        raise HTTPException(status_code=415, detail=f"{filename} isn't a real {TYPE_NAME[expected]}. "
                                                    "The file may be damaged or have the wrong extension.")
    if actual != expected:
        raise HTTPException(status_code=415, detail=f"{filename} is named as {a_or_an(TYPE_NAME[expected])} but is "
                                                    f"really {a_or_an(TYPE_NAME[actual])}. Rename it or choose the "
                                                    "right file.")
    if damaged(actual, data):
        raise HTTPException(status_code=422, detail=f"{filename} looks damaged or incomplete, so it can't be uploaded.")
    return actual


async def read_upload(upload: UploadFile, filename: str) -> bytes:
    """The file's bytes, read in pieces: stops as soon as it is larger than the limit."""
    chunks, total = [], 0
    while chunk := await upload.read(READ_CHUNK):
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{filename} is larger than 20 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def content_disposition(kind: str, filename: str) -> str:
    """inline / attachment plus the file name: plain ASCII for old browsers, UTF-8 (RFC 6266) for the rest."""
    fallback = re.sub(r"[^A-Za-z0-9._() -]", "_", filename) or "file"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


# ---------- helpers ----------

# Files can be added while the deal is open, and to a Won deal (e.g. the signed order); never to a Lost one.
# Deleting stays limited to open deals.
UPLOAD_STAGES = [*OPPORTUNITY_OPEN_STAGES, "Won"]


def ensure_files_open(opp: Opportunity, action: str, stages=OPPORTUNITY_OPEN_STAGES) -> None:
    if opp.stage not in stages:
        raise HTTPException(status_code=409, detail=f"This opportunity is {opp.stage}, so files can't be {action} any more. "
                                                    "Its files can still be viewed and downloaded.")


def locked_opportunity(db: Session, opportunity_id: int) -> Opportunity:
    """The opportunity, locked until the save: its stage can't change while a file is added or deleted."""
    opp = db.get(Opportunity, opportunity_id, with_for_update=True, populate_existing=True)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    return opp


def find_attachment(db: Session, opportunity_id: int, attachment_id: int, *, with_data: bool = False) -> OpportunityAttachment:
    """A file of this opportunity that is not deleted (an id from another opportunity is "not found")."""
    query = select(OpportunityAttachment).where(
        OpportunityAttachment.id == attachment_id,
        OpportunityAttachment.opportunity_id == opportunity_id,
        OpportunityAttachment.deleted_at.is_(None),
    )
    if with_data:
        query = query.options(undefer(OpportunityAttachment.data))
    item = db.scalars(query).first()
    if item is None:
        raise HTTPException(status_code=404, detail=f"Attachment {attachment_id} not found")
    return item


def attachment_out(a: OpportunityAttachment) -> schemas.OpportunityAttachmentOut:
    return schemas.OpportunityAttachmentOut.model_validate(a).model_copy(
        update={"uploaded_by_name": a.uploaded_by.full_name if a.uploaded_by else None}
    )


# ---------- APIs ----------

@router.get("/{opportunity_id}/attachments", response_model=list[schemas.OpportunityAttachmentOut])
def list_attachments(opportunity_id: int, db: Session = Depends(get_db)):
    """The files of an opportunity, newest first (deleted files are not listed)."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_view(opp.owner_id, "opportunity")
    rows = db.scalars(
        select(OpportunityAttachment)
        .options(joinedload(OpportunityAttachment.uploaded_by))
        .where(OpportunityAttachment.opportunity_id == opp.id, OpportunityAttachment.deleted_at.is_(None))
        .order_by(OpportunityAttachment.uploaded_at.desc(), OpportunityAttachment.id.desc())
    ).all()
    return [attachment_out(a) for a in rows]


@router.post("/{opportunity_id}/attachments", response_model=schemas.OpportunityAttachmentOut,
             status_code=status.HTTP_201_CREATED, openapi_extra=UPLOAD_FORM)
async def upload_attachment(opportunity_id: int, request: Request, db: Session = Depends(get_db)):
    """Add one file (form field "file"): PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), JPG or PNG, up to 20 MB.
    While the deal is open (Opportunity, Discovery or Proposal) or Won, by someone who can edit the opportunity. The
    file is saved with the deal's stage at that moment (e.g. Won) and the uploader."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    me = require_edit(opp.owner_id, "opportunity")
    ensure_files_open(opp, "added", UPLOAD_STAGES)
    # the size is checked before anything is read; the server never accepts more than Content-Length
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(status_code=411, detail="Upload one file at a time (the request has no size).")
    if int(length) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 20 MB.")
    async with request.form(max_files=1, max_fields=0) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail='Choose a file to upload (form field "file").')
        filename = clean_filename(upload.filename)
        if not filename:
            raise HTTPException(status_code=422, detail="The file needs a name.")
        data = await read_upload(upload, filename)
    content_type = checked_type(filename, data)

    opp = locked_opportunity(db, opportunity_id)
    ensure_files_open(opp, "added", UPLOAD_STAGES)  # it may have been closed as Lost while the file was uploading
    attachment = OpportunityAttachment(
        opportunity_id=opp.id, stage=opp.stage, filename=filename, content_type=content_type,
        size_bytes=len(data), data=data, uploaded_by_id=me.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment_out(attachment)


@router.get("/{opportunity_id}/attachments/{attachment_id}/file")
def attachment_file(
    opportunity_id: int,
    attachment_id: int,
    download: bool = Query(False, description="true: save as a file. false: PDF and images open in the browser"),
    db: Session = Depends(get_db),
):
    """The file itself, with the type the server detected at upload. Never cached by the browser."""
    opp = get_or_404(db, Opportunity, opportunity_id, "Opportunity")
    require_view(opp.owner_id, "opportunity")
    item = find_attachment(db, opp.id, attachment_id, with_data=True)
    inline = not download and item.content_type in PREVIEW_TYPES
    return Response(
        content=item.data,
        media_type=item.content_type,
        headers={
            "Content-Disposition": content_disposition("inline" if inline else "attachment", item.filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{opportunity_id}/attachments/{attachment_id}")
def delete_attachment(opportunity_id: int, attachment_id: int, db: Session = Depends(get_db)):
    """Hide a file (it is kept in the database with who deleted it and when).
    Needs edit access, an open stage, and to be the uploader or a Manager / Admin."""
    opp = locked_opportunity(db, opportunity_id)
    me = require_edit(opp.owner_id, "opportunity")
    ensure_files_open(opp, "deleted")
    item = find_attachment(db, opp.id, attachment_id)
    if item.uploaded_by_id != me.id and me.role not in ("Manager", "Admin"):
        raise HTTPException(status_code=403, detail="Only the person who uploaded this file, or a Manager or Admin, can delete it.")
    item.deleted_at, item.deleted_by_id = now(), me.id
    uploader = item.uploaded_by.full_name if item.uploaded_by else "unknown user"
    log_activity(db, me.id, "Attachment deleted", f"{opp.name} • {item.filename}",
                 f"Uploaded by {uploader} at the {item.stage} stage")
    db.commit()
    return {"deleted": True, "id": attachment_id}
