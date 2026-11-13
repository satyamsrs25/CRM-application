"""Accounts (companies) and Contacts (people). Usually created by converting a lead; can also be added directly.
No duplicates: one account per company (name or website) and one contact per email (app/opportunity_matches.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app import schemas
from app.database import get_db
from app.security import acting_user, can_view, owner_for_new, require_view, visible
from app import opportunity_matches as matches
from app.constants import LEAD_OPEN_STAGES
from app.models import Account, Contact, Email, Lead, Opportunity, Task
from app.serializers import account_detail, account_out, contact_out
from app.services import activity_of, get_or_404, resolve_user_id

router = APIRouter(prefix="/api", tags=["Accounts and contacts"])


def _worked_on(user_id: int):
    """Accounts where the user has a contact or an opportunity. One company has one account, so a salesperson whose deal
    is on another salesperson's account can still open that account (and sees only their own contacts and deals there)."""
    return or_(Account.id.in_(select(Opportunity.account_id).where(Opportunity.owner_id == user_id)),
               Account.id.in_(select(Contact.account_id).where(Contact.owner_id == user_id)))


@router.get("/accounts", response_model=list[schemas.AccountOut])
def list_accounts(
    search: str | None = Query(None), owner_id: int | None = Query(None), db: Session = Depends(get_db)
):
    me = acting_user()
    query = select(Account) if me.sees_team else select(Account).where(or_(Account.owner_id == me.id, _worked_on(me.id)))
    if owner_id is not None:
        query = query.where(Account.owner_id == owner_id)
    if search:
        query = query.where(Account.name.ilike(f"%{search.strip()}%"))
    accounts = db.scalars(query.options(joinedload(Account.owner)).order_by(Account.name)).all()
    latest = last_activity(db, [a.id for a in accounts])
    activity = activity_of(db, Account, [a.id for a in accounts])
    out = []
    for a in accounts:
        row = account_out(a)
        stamps = [s for s in (a.updated_at, a.created_at, latest.get(a.id)) if s]
        out.append(row.model_copy(update={"last_activity_at": max(stamps) if stamps else None,
                                          "activity": activity.get(a.id)}))
    return out


def last_activity(db: Session, account_ids: list[int]) -> dict[int, datetime]:
    """Accounts list > Last Activity: the latest update to each account's contacts, opportunities, their tasks, or an
    email sent to the account, its contacts or its deals."""
    if not account_ids:
        return {}
    latest: dict[int, datetime] = {}

    def take(rows):
        for account_id, stamp in rows:
            if account_id is not None and stamp is not None and (account_id not in latest or stamp > latest[account_id]):
                latest[account_id] = stamp

    take(db.execute(select(Contact.account_id, func.max(Contact.updated_at))
                    .where(Contact.account_id.in_(account_ids)).group_by(Contact.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Opportunity.updated_at))
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Task.updated_at)).join(Task, Task.opportunity_id == Opportunity.id)
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    take(db.execute(select(Email.account_id, func.max(Email.sent_at))
                    .where(Email.account_id.in_(account_ids)).group_by(Email.account_id)).all())
    take(db.execute(select(Contact.account_id, func.max(Email.sent_at)).join(Email, Email.contact_id == Contact.id)
                    .where(Contact.account_id.in_(account_ids)).group_by(Contact.account_id)).all())
    take(db.execute(select(Opportunity.account_id, func.max(Email.sent_at)).join(Email, Email.opportunity_id == Opportunity.id)
                    .where(Opportunity.account_id.in_(account_ids)).group_by(Opportunity.account_id)).all())
    return latest


def _match(record, why: str, **fields) -> dict:
    """A duplicate the form shows: a link when the user can open it, otherwise only its owner."""
    return {"id": record.id if can_view(record.owner_id) else None, "why": why,
            "owner": record.owner.full_name if record.owner else None, "mine": record.owner_id == acting_user().id,
            **fields}


@router.get("/accounts/duplicates")
def account_duplicates(name: str | None = Query(None, max_length=200), website: str | None = Query(None, max_length=255),
                       db: Session = Depends(get_db)):
    """While typing a new account: the account that already has this company name or website."""
    found = []
    by_name = matches.find_account(db, name)
    if by_name is not None:
        found.append(_match(by_name, "name", name=by_name.name, website=by_name.website))
    by_site = matches.find_account_by_website(db, website)
    if by_site is not None and by_site is not by_name:
        found.append(_match(by_site, "website", name=by_site.name, website=by_site.website))
    return {"matches": found}


@router.post("/accounts", response_model=schemas.AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(data: schemas.AccountCreate, db: Session = Depends(get_db)):
    matches.ensure_new_account(db, data.name, data.website)  # one account per company (name or website)
    account = Account(**data.model_dump(exclude={"owner_id"}), owner_id=resolve_user_id(db, owner_for_new(data.owner_id)))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_out(account)


@router.get("/accounts/{account_id}", response_model=schemas.AccountDetail)
def get_account(account_id: int, db: Session = Depends(get_db)):
    """The account page: details, its contacts and its opportunities."""
    account = get_or_404(db, Account, account_id, "Account")
    me = acting_user()
    if not can_view(account.owner_id) and not db.scalar(select(Account.id).where(Account.id == account.id,
                                                                                   _worked_on(me.id))):
        require_view(account.owner_id, "account")  # 404, like any record the user can't open
    detail = account_detail(account)
    if not me.sees_team:  # without team access: only your own contacts and deals on the account
        detail.contacts = [c for c in detail.contacts if c.owner_id == me.id]
        detail.opportunities = [o for o in detail.opportunities if o.owner_id == me.id]
    return detail


@router.get("/contacts", response_model=list[schemas.ContactOut])
def list_contacts(
    account_id: int | None = Query(None), search: str | None = Query(None), db: Session = Depends(get_db)
):
    query = visible(select(Contact), Contact)
    if account_id is not None:
        query = query.where(Contact.account_id == account_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Contact.full_name.ilike(like), Contact.email.ilike(like)))
    query = query.options(joinedload(Contact.account))  # the account name in the same query, not one query per contact
    contacts = db.scalars(query.order_by(Contact.last_name, Contact.first_name)).all()
    activity = activity_of(db, Contact, [c.id for c in contacts])  # for Home's Contacts card pills
    return [contact_out(c).model_copy(update={"activity": activity.get(c.id)}) for c in contacts]


def contact_matches(db: Session, email: str | None, account_id: int | None = None, first_name: str | None = None,
                    last_name: str | None = None) -> list[dict]:
    """The contact with this email (any account), the same person on this account, and an open lead with the email."""
    found = []
    by_email = matches.find_contact_by_email(db, email)
    if by_email is not None:
        found.append(_match(by_email, "email", type="Contact", name=by_email.full_name,
                            account=by_email.account.name if by_email.account else None))
    if last_name and account_id is not None:
        by_name = matches.find_contact(db, account_id, first_name=first_name, last_name=last_name)
        if by_name is not None and by_name is not by_email:
            found.append(_match(by_name, "name", type="Contact", name=by_name.full_name,
                                account=by_name.account.name if by_name.account else None))
    clean = (email or "").strip().lower()
    if clean:
        lead = db.scalars(select(Lead).where(func.lower(Lead.email) == clean, Lead.stage.in_(LEAD_OPEN_STAGES))).first()
        if lead is not None:
            found.append(_match(lead, "lead", type="Lead", name=lead.name, account=lead.company))
    return found


@router.get("/contacts/duplicates")
def contact_duplicates(email: str | None = Query(None, max_length=255), account_id: int | None = Query(None),
                       first_name: str | None = Query(None, max_length=50), last_name: str | None = Query(None, max_length=50),
                       db: Session = Depends(get_db)):
    """While typing a new contact: who already has this email, or the same name on this account."""
    return {"matches": contact_matches(db, email, account_id, first_name, last_name)}


@router.post("/contacts", response_model=schemas.ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(data: schemas.ContactCreate, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, data.account_id, "Account")
    require_view(account.owner_id, "account")
    # one contact per person: not an email another contact has, the same name on this account, or an open lead's email
    found = contact_matches(db, data.email, account.id, data.first_name, data.last_name)
    if found:
        first = found[0]
        where = f' at {first["account"]}' if first["account"] else ""
        owner = "yours" if first["mine"] else f'owned by {first["owner"]}'
        what = {"email": "already has this email", "name": "has the same name on this account",
                "lead": "is an open lead with this email: convert the lead instead"}[first["why"]]
        raise HTTPException(status_code=409, detail=(
            f'{first["type"]} {first["name"]}{where} ({owner}) {what}. One person has one contact.'))
    contact = Contact(  # phone: already checked for its country and in international format (schemas.ContactCreate)
        **data.model_dump(exclude={"owner_id", "phone_country"}), owner_id=resolve_user_id(db, owner_for_new(data.owner_id))
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact_out(contact)


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = get_or_404(db, Contact, contact_id, "Contact")
    require_view(contact.owner_id, "contact")
    return contact_out(contact)
