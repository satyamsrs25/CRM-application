"""The same phone number on more than one lead or contact.

Agreed behaviour (New Lead and Edit Lead, when the phone is new or changed):
- Blocked: the number is already on an open lead, or on a contact, for the same person (same first + last name).
  That is a duplicate lead: use the existing record (or ask for it to be transferred).
- Warning: the number is on other records for other people. Companies often share one business number (a reception
  or switchboard line), so this is allowed once the user confirms it ("Save anyway": confirm_shared_phone). The
  warning names the records (only the owner for records the user can't open), and says when they are at the same
  company, the usual shared-number case.
Numbers are compared by their digits, ignoring spaces, brackets, the + and the country code / trunk 0 (the last 10
digits), so "+91 98765 43210", "098765 43210" and "9876543210" are the same number. Uploads and the AI Assistant
don't stop for this.
"""
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import LEAD_OPEN_STAGES
from app.models import Contact, Lead
from app.security import acting_user, can_view

MIN_DIGITS = 7  # shorter numbers (extensions, typos) are never compared


def phone_key(value: str | None) -> str:
    """'+91 98765 43210' -> '9876543210': the number's last 10 digits ("" for too short a number)."""
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= MIN_DIGITS else ""


def _like(key: str) -> str:
    """A LIKE pattern for a stored number that ends in these digits whatever separators it has ('%3%2%1%0')."""
    return "%" + "%".join(key[-4:])


def _person(first: str | None, last: str | None) -> str:
    return " ".join(f"{first or ''} {last or ''}".lower().split())


def _company(name: str | None) -> str:
    from app.routers.lead_files import company_key  # the same company comparison as the company box
    return company_key(name)


def find_phone_matches(db: Session, phone: str | None, *, first_name: str | None = None, last_name: str | None = None,
                       company: str | None = None, exclude_lead_id: int | None = None) -> list[dict]:
    """Leads (any stage) and contacts with this phone number, newest first. `same_person` / `same_company` say why
    it matters; `blocks` marks the records that make it a duplicate (an open lead or a contact of the same person)."""
    key = phone_key(phone)
    if not key:
        return []
    me = acting_user()
    person, company_name = _person(first_name, last_name), _company(company)
    found = []
    leads = db.scalars(select(Lead).options(selectinload(Lead.owner)).where(Lead.phone.like(_like(key)))
                       .order_by(Lead.id.desc()).limit(500)).all()
    for lead in leads:
        if lead.id == exclude_lead_id or phone_key(lead.phone) != key:
            continue
        same_person = bool(person) and _person(lead.first_name, lead.last_name) == person
        open_lead = lead.stage in LEAD_OPEN_STAGES
        visible = lead.owner_id == me.id or me.sees_team
        found.append({"type": "Lead", "id": lead.id if visible else None, "name": lead.name if visible else None,
                      "company": lead.company, "stage": lead.stage, "open": open_lead,
                      "owner_id": lead.owner_id, "owner_name": lead.owner.full_name if lead.owner else None,
                      "can_open": visible, "same_person": same_person,
                      "same_company": bool(company_name) and _company(lead.company) == company_name,
                      "blocks": same_person and open_lead})
    contacts = db.scalars(select(Contact).options(selectinload(Contact.owner), selectinload(Contact.account))
                          .where(Contact.phone.like(_like(key))).order_by(Contact.id.desc()).limit(500)).all()
    for contact in contacts:
        if phone_key(contact.phone) != key:
            continue
        same_person = bool(person) and _person(contact.first_name, contact.last_name) == person
        account = contact.account.name if contact.account else None
        visible = can_view(contact.owner_id)
        found.append({"type": "Contact", "id": contact.id if visible else None,
                      "name": contact.full_name if visible else None, "company": account, "stage": None, "open": False,
                      "owner_id": contact.owner_id, "owner_name": contact.owner.full_name if contact.owner else None,
                      "can_open": visible, "same_person": same_person,
                      "same_company": bool(company_name) and _company(account) == company_name,
                      "blocks": same_person})
    found.sort(key=lambda m: (not m["blocks"], not m["same_company"], not m["open"]))
    return found


def describe(match: dict) -> str:
    """'lead Mira Shah (Brightline Logistics, New), owner Priya Sharma' (only the owner when the user can't open it)."""
    if not match["can_open"]:
        return f'a {match["type"].lower()} owned by {match["owner_name"] or "another user"}'
    what = f'{match["company"] or "no company"}{", " + match["stage"] if match["stage"] else ""}'
    return f'{match["type"].lower()} {match["name"]} ({what}), owner {match["owner_name"]}'


def phone_message(matches: list[dict]) -> tuple[bool, str]:
    """(blocked, the message) for these matches."""
    blocking = [m for m in matches if m["blocks"]]
    if blocking:
        m = blocking[0]
        what = "an open lead" if m["type"] == "Lead" else "a contact"
        return True, (f"This person is already {what} with this phone number: {describe(m)}. "
                      "Use that record instead of adding a duplicate lead.")
    named = [describe(m) for m in matches if m["can_open"]]
    hidden: dict[tuple[str, str], int] = {}  # records the user can't open: counted per owner, without names
    for m in matches:
        if not m["can_open"]:
            key = (m["type"].lower(), m["owner_name"] or "another user")
            hidden[key] = hidden.get(key, 0) + 1
    parts = named[:2] + [f"{n} {kind}{'s' if n > 1 else ''} owned by {owner}" for (kind, owner), n in hidden.items()]
    shown = ", ".join(parts)
    more = f" and {len(named) - 2} more" if len(named) > 2 else ""
    shared = any(m["same_company"] for m in matches)
    return False, (f"This phone number is also on {shown}{more}. "
                   + ("It looks like a shared business number for this company. " if shared else "")
                   + "If it is a shared number (e.g. a reception line), save again to keep it.")


def check_lead_phone(db: Session, phone: str | None, *, first_name: str | None, last_name: str | None,
                     company: str | None, exclude_lead_id: int | None = None, confirmed: bool = False) -> None:
    """New Lead / Edit Lead: refuses a duplicate person's number; asks once about a number other records have."""
    matches = find_phone_matches(db, phone, first_name=first_name, last_name=last_name, company=company,
                                 exclude_lead_id=exclude_lead_id)
    if not matches:
        return
    blocked, message = phone_message(matches)
    if blocked or not confirmed:
        raise HTTPException(status_code=409, detail=message)
