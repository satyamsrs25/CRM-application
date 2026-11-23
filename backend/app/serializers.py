"""Turn database rows into API responses, adding readable names (owner, account, related record)."""
from sqlalchemy.orm import object_session

from app import schemas
from app.models import Account, Contact, Lead, Note, Opportunity, StageHistory, Task
from app.security import sees_pool_contacts
from app.services import demo_instant, is_date_reminder, start_of_today, task_related
from app.stage_clock import Clock, stage_clocks

# A pooled lead (no owner) seen by someone who can't assign it: everything but how to reach the person
# hidden on a pooled lead from users who can only request it. Its Region (phone_country, the country only) stays
# visible and filterable for everyone who may list the lead
POOL_CONTACT_FIELDS = ("email", "phone", "linkedin_url")


def task_out(t: Task) -> schemas.TaskOut:
    related_type, related_to = task_related(t)
    return schemas.TaskOut.model_validate(t).model_copy(
        update={
            "owner_name": t.owner.full_name if t.owner else None,
            "related_type": related_type,
            "related_to": related_to,
            "is_overdue": t.status == "Open" and t.due_date < start_of_today(),
            "is_date_reminder": is_date_reminder(t),
        }
    )


def note_out(n: Note) -> schemas.NoteOut:
    return schemas.NoteOut.model_validate(n).model_copy(
        update={"created_by_name": n.created_by.full_name if n.created_by else None}
    )


def history_out(h: StageHistory) -> schemas.StageHistoryOut:
    return schemas.StageHistoryOut.model_validate(h).model_copy(
        update={"changed_by_name": h.changed_by.full_name if h.changed_by else None}
    )


def pool_summary_only(lead: Lead) -> bool:
    """A pooled lead shown to a user who can only request it: its contact details stay hidden."""
    return lead.owner_id is None and not sees_pool_contacts()


def owner_since(lead: Lead):
    """When the current owner got the lead: the saved assignment time, else (older leads) the latest transfer when it
    went to this owner. None when it was never recorded (no date is made up)."""
    if lead.owner_id is None:
        return None
    if lead.assigned_at is not None:
        return lead.assigned_at
    last = lead.transfers[-1] if lead.transfers else None
    return last.transferred_at if last is not None and last.to_user_id == lead.owner_id else None


def lead_out(lead: Lead) -> schemas.LeadOut:
    hidden = pool_summary_only(lead)
    return schemas.LeadOut.model_validate(lead).model_copy(
        update={
            **({field: None for field in POOL_CONTACT_FIELDS} if hidden else {}),
            "contact_hidden": hidden,
            "in_pool": lead.owner_id is None,
            "owner_since": owner_since(lead),
            "owner_name": lead.owner.full_name if lead.owner else None,
            "opportunity_id": lead.opportunity.id if lead.opportunity else None,
            "created_by_name": lead.created_by.full_name if lead.created_by else None,
            # the latest transfer: to whom and when (Transferred To / Transferred At in the list)
            "last_transferred_at": lead.transfers[-1].transferred_at if lead.transfers else None,
            "last_transferred_to": lead.transfers[-1].to_user.full_name if lead.transfers and lead.transfers[-1].to_user
            else None,
            "demo_at": demo_instant(lead.demo_date),
        }
    )


def lead_detail(lead: Lead) -> schemas.LeadDetail:
    base = lead_out(lead).model_dump()
    # In stage on the lead page: the Leads list's clock (app/stage_clock.py), its own reference time for this answer
    session = object_session(lead)
    base["in_stage"] = stage_clocks(session, Clock(), [lead.id]).get(lead.id) if session is not None else None
    summary = base["contact_hidden"]  # a pooled lead for someone who can only request it: no tasks or notes either
    return schemas.LeadDetail(
        **base,
        tasks=[] if summary else [task_out(t) for t in sorted(lead.tasks, key=lambda t: (t.status != "Open", t.due_date))],
        notes=[] if summary else [note_out(n) for n in sorted(lead.notes, key=lambda n: n.id, reverse=True)],
        history=[history_out(h) for h in sorted(lead.history, key=lambda h: h.id)],
        transfers=[transfer_out(t) for t in sorted(lead.transfers, key=lambda t: t.id, reverse=True)],
    )


def transfer_out(t) -> schemas.LeadTransferOut:
    return schemas.LeadTransferOut.model_validate(t).model_copy(update={
        "from_user_name": t.from_user.full_name if t.from_user else None,
        "to_user_name": t.to_user.full_name if t.to_user else None,
        "transferred_by_name": t.transferred_by.full_name if t.transferred_by else None,
    })


def account_out(a: Account) -> schemas.AccountOut:
    return schemas.AccountOut.model_validate(a).model_copy(update={"owner_name": a.owner.full_name if a.owner else None})


def contact_out(c: Contact) -> schemas.ContactOut:
    return schemas.ContactOut.model_validate(c).model_copy(update={"account_name": c.account.name if c.account else None})


def opportunity_out(o: Opportunity) -> schemas.OpportunityOut:
    return schemas.OpportunityOut.model_validate(o).model_copy(
        update={
            "account_name": o.account.name if o.account else None,
            "primary_contact_name": o.primary_contact.full_name if o.primary_contact else None,
            "lead_name": o.lead.name if o.lead else None,
            "owner_name": o.owner.full_name if o.owner else None,
        }
    )


def opportunity_detail(o: Opportunity) -> schemas.OpportunityDetail:
    base = opportunity_out(o).model_dump()
    return schemas.OpportunityDetail(
        **base,
        tasks=[task_out(t) for t in sorted(o.tasks, key=lambda t: (t.status != "Open", t.due_date))],
        notes=[note_out(n) for n in sorted(o.notes, key=lambda n: n.id, reverse=True)],
        history=[history_out(h) for h in sorted(o.history, key=lambda h: h.id)],
    )


def account_detail(a: Account) -> schemas.AccountDetail:
    base = account_out(a).model_dump()
    return schemas.AccountDetail(
        **base,
        contacts=[contact_out(c) for c in a.contacts],
        opportunities=[opportunity_out(o) for o in a.opportunities],
    )
