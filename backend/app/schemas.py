"""What each API accepts (request body) and returns (response).

Field names match the PostgreSQL tables in database/schema.sql.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

import re
from urllib.parse import quote, unquote, urlsplit

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.constants import LEAD_SOURCE_DETAIL_MAX

LeadSource = Literal["Website", "LinkedIn", "Referral", "Phone", "Email", "Event", "Social Media", "Other", "Upload"]
LostReason = Literal["Price", "Competitor", "No response", "No budget", "Not interested", "Other"]
UnqualifiedReason = Literal["Not a fit", "No budget", "No authority", "No current need", "Bad timing", "Bad data", "Other"]
RevisitReason = Literal["Bad timing", "Budget next period", "Asked to call back", "No response yet", "Demo cancelled",
                        "Other"]
Priority = Literal["Low", "Normal", "High"]
Salutation = Literal["Mr.", "Ms.", "Mrs.", "Dr.", "Prof."]
Currency = Literal["USD", "INR", "EUR", "CAD", "AUD", "AED"]  # constants.CURRENCIES
UserRole = Literal["Salesperson", "Manager", "Admin"]
LeadOpenStage = Literal["New", "Nurturing", "Revisit", "Demo"]      # constants.LEAD_FLOW
OpportunityOpenStage = Literal["Opportunity", "Discovery", "Proposal"]            # constants.OPPORTUNITY_FLOW


class Out(BaseModel):
    """Base for responses: reads ORM objects and sends money as numbers (not strings)."""

    model_config = ConfigDict(from_attributes=True)


def money(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


# ---------- Users and login ----------

class UserOut(Out):
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    email_stage_updates: bool = False
    email_assignments: bool = True
    email_reminders: bool = True
    team_access: bool = False
    created_at: datetime | None = None
    role_changed_at: datetime | None = None
    access_changed_at: datetime | None = None
    reports_to_id: int | None = None    # a Salesperson's Manager
    reports_to_name: str | None = None
    permissions: list[str] = []  # filled for the logged-in user (login, /auth/me)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    """Admin adds a user (there is no public sign up)."""
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = "Salesperson"
    reports_to_id: int | None = None  # a Salesperson's Manager (a Manager adding someone: always themselves)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=100)
    email: str | None = Field(None, max_length=255)  # the login username
    role: UserRole | None = None
    is_active: bool | None = None
    reports_to_id: int | None = None  # 0 = no Manager


class ProfileUpdate(BaseModel):
    """What a user can change on their own profile (email and role are changed by the Admin).
    Send only what changes."""
    full_name: str | None = Field(None, min_length=2, max_length=100)
    email_stage_updates: bool | None = None  # email me when my leads / deals move to the next stage
    email_assignments: bool | None = None    # email me when something is assigned to me
    email_reminders: bool | None = None      # email me reminders (tasks, demos, close dates, overdue)


class TeamAccess(BaseModel):
    team_access: bool


class PermissionChange(BaseModel):
    role: UserRole
    permission: str
    allowed: bool


class PasswordReset(BaseModel):
    """Admin sets a new password for a user."""
    password: str = Field(..., min_length=8, max_length=128)


class PasswordChange(BaseModel):
    """A user changes their own password."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class TransferRecords(BaseModel):
    """Move everything a user owns to another user (e.g. when someone leaves)."""
    to_user_id: int
    deactivate: bool = False


class TestEmail(BaseModel):
    to: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginResponse(BaseModel):
    message: str
    user: UserOut
    token: str  # send as "Authorization: Bearer <token>" on every request


# ---------- History, tasks, notes (shown on record pages) ----------

class StageHistoryOut(Out):
    id: int
    from_stage: str | None
    to_stage: str
    note: str | None
    changed_at: datetime | None
    changed_by_id: int
    changed_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None


class TaskOut(Out):
    id: int
    title: str
    description: str | None
    due_date: datetime
    reminder_at: datetime | None
    status: str
    priority: str
    is_auto: bool
    completed_at: datetime | None
    owner_id: int
    owner_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    related_type: str | None = None
    related_to: str | None = None
    is_overdue: bool = False
    # a date reminder (e.g. the close-date reminder): not stage work, so it never holds up moving a deal forward
    is_date_reminder: bool = False
    created_at: datetime | None


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime
    reminder_at: datetime | None = None
    priority: Priority = "Normal"
    owner_id: int | None = None  # default: owner of the lead/opportunity, else the first user
    lead_id: int | None = None
    opportunity_id: int | None = None
    created_by_id: int | None = None  # logged-in user; the owner is notified when someone else assigns it


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    reminder_at: datetime | None = None
    priority: Priority | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)


class NoteOut(Out):
    id: int
    body: str
    created_by_id: int
    created_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    created_at: datetime | None


class NoteCreate(BaseModel):
    body: str = Field(..., min_length=1)
    created_by_id: int | None = None
    lead_id: int | None = None
    opportunity_id: int | None = None


# ---------- Leads ----------

def clean_url(value: str | None, *, linkedin: bool = False) -> str | None:
    """'linkedin.com/in/x' -> 'https://linkedin.com/in/x'. Empty -> None. LinkedIn fields must point to linkedin.com."""
    value = (value or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = re.sub(r"^https?://", "", value, flags=re.I).split("/")[0].lower()
    if "." not in host or " " in value:
        raise ValueError("Enter a valid web address")
    if linkedin and not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        raise ValueError("Enter a LinkedIn address (linkedin.com/...)")
    return value


PROFILE_HOST = re.compile(r"(?:www\.|[a-z]{2}\.)?linkedin\.com")  # also country sites such as uk.linkedin.com
PROFILE_NAME = re.compile(r"[\w-]{3,100}")  # letters (any language), digits, - and _


def linkedin_profile_url(value: str | None) -> str:
    """A person's LinkedIn profile (linkedin.com/in/<name>) in one form: https://linkedin.com/in/<name>.
    Raises ValueError for anything else: company or school pages, sites that only look like LinkedIn, other schemes,
    a login or port in the address, short links (lnkd.in) and extra path parts. Query and #fragment are dropped."""
    raw = (value or "").strip()
    if not raw or len(raw) > 300 or any(ch.isspace() for ch in raw):
        raise ValueError("Enter a LinkedIn profile address like https://www.linkedin.com/in/name")
    if "://" not in raw:
        if raw.startswith("/") or ":" in raw.split("/")[0]:
            raise ValueError("Enter a LinkedIn profile address like https://www.linkedin.com/in/name")
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Only https:// LinkedIn profile addresses can be used")
    try:
        port = parts.port
    except ValueError:
        port = -1
    host = (parts.hostname or "").lower()
    if "@" in parts.netloc or port is not None or not PROFILE_HOST.fullmatch(host):
        raise ValueError("This isn't a linkedin.com profile address")
    match = re.fullmatch(r"/in/([^/]+)/?", parts.path)
    if not match:
        raise ValueError("Use a person's profile address (linkedin.com/in/...), not a company, school or other page")
    name = unquote(match.group(1))
    if not PROFILE_NAME.fullmatch(name):
        raise ValueError("This LinkedIn profile address isn't valid")
    return f"https://linkedin.com/in/{quote(name.lower(), safe='-_')}"


class LeadLinks(BaseModel):
    """Research links and company size on a lead (New Lead / Edit Lead / import)."""

    linkedin_url: str | None = Field(None, max_length=300)
    company_website: str | None = Field(None, max_length=255)
    company_linkedin_url: str | None = Field(None, max_length=300)
    annual_revenue: Decimal | None = Field(None, ge=0, le=Decimal("99999999999999"))  # turnover, in `currency`
    employees: int | None = Field(None, ge=0, le=10_000_000)  # headcount
    location: str | None = Field(None, max_length=200)

    @field_validator("linkedin_url", "company_linkedin_url")
    @classmethod
    def _linkedin(cls, v):
        return clean_url(v, linkedin=True)

    @field_validator("company_website")
    @classmethod
    def _website(cls, v):
        return clean_url(v)

    @field_validator("location")
    @classmethod
    def _location(cls, v):
        return " ".join(v.split()) or None if v else None


# New Lead rules (the form, the API and the AI Assistant). Older leads may lack these values: an edit enforces a rule
# only when it changes that field or the Lead Source (routers/leads.py, update_lead).
FIRST_NAME_REQUIRED = "Enter the lead's first name."
SOURCE_DETAIL_REQUIRED = "Specify the lead source (required when Lead Source is Other)."
LINKEDIN_PROFILE_REQUIRED = "Enter the lead's LinkedIn Profile URL (required when Lead Source is LinkedIn)."
SOURCE_DETAIL_MAX = LEAD_SOURCE_DETAIL_MAX  # leads.source_detail VARCHAR(100)


def trimmed(value):
    """Spaces around a text are dropped; only spaces counts as empty (None)."""
    return (value.strip() or None) if isinstance(value, str) else value


class LeadCreate(LeadLinks):
    """Like the Salesforce "New Lead" form: First Name, Last Name and Company are required. Lead Source LinkedIn needs
    the LinkedIn Profile URL; Other needs source_detail (what the source is)."""

    salutation: Salutation | None = None
    first_name: Annotated[str | None, BeforeValidator(trimmed)] = Field(None, max_length=50)  # required: checked below
    last_name: str = Field(..., min_length=1, max_length=50)
    company: str = Field(..., min_length=1, max_length=200)
    title: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    source: LeadSource = "Other"
    source_detail: Annotated[str | None, BeforeValidator(trimmed)] = Field(None, max_length=SOURCE_DETAIL_MAX)
    currency: Currency = "USD"  # of the turnover
    owner_id: int | None = None  # default: the logged-in user
    created_by_id: int | None = None  # ignored: the logged-in user creates it
    confirm_email_domain: bool = False  # the user checked the email is right though its domain differs from the website

    @field_validator("linkedin_url")
    @classmethod
    def _profile(cls, v):
        """A person's profile address is saved in one form (other LinkedIn links stay as typed)."""
        try:
            return linkedin_profile_url(v) if v else v
        except ValueError:
            return v

    @model_validator(mode="after")
    def _new_lead_rules(self):
        if not self.first_name:
            raise ValueError(FIRST_NAME_REQUIRED)
        if self.source == "Other" and not self.source_detail:
            raise ValueError(SOURCE_DETAIL_REQUIRED)
        if self.source == "LinkedIn" and not self.linkedin_url:
            raise ValueError(LINKEDIN_PROFILE_REQUIRED)
        if self.source != "Other":
            self.source_detail = None  # only Other has a description
        return self


class LeadUpdate(LeadLinks):
    """Send only the fields to change. Stage changes use /stage, /lost and /convert."""

    salutation: Salutation | None = None
    first_name: Annotated[str | None, BeforeValidator(trimmed)] = Field(None, max_length=50)
    last_name: str | None = Field(None, min_length=1, max_length=50)
    company: str | None = Field(None, min_length=1, max_length=200)
    title: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    source: LeadSource | None = None
    source_detail: Annotated[str | None, BeforeValidator(trimmed)] = Field(None, max_length=SOURCE_DETAIL_MAX)
    currency: Currency | None = None
    demo_date: datetime | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)
    confirm_email_domain: bool = False  # not saved: the user checked the email is right (see LeadCreate)


class LeadOut(Out):
    id: int
    salutation: str | None
    first_name: str | None
    last_name: str
    name: str  # first + last name, filled automatically
    company: str | None
    title: str | None
    industry: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None = None
    company_website: str | None = None
    company_linkedin_url: str | None = None
    annual_revenue: Decimal | None = None
    currency: str = "USD"
    employees: int | None = None
    location: str | None = None
    untouched: bool = False  # uploaded and not worked on yet
    uploaded_from: str | None = None  # file name when the lead came from a bulk upload
    source: str
    source_detail: str | None = None  # Lead Source Other: what the source is (older Other leads may have none)
    stage: str
    demo_date: datetime | None  # server time, no zone (as stored)
    demo_at: datetime | None = None  # the same moment in UTC: the app shows it in IST and calendars use it
    lost_reason: str | None
    lost_notes: str | None
    unqualified_reason: str | None = None
    unqualified_notes: str | None = None
    revisit_date: datetime | None = None
    revisit_reason: str | None = None
    converted_at: datetime | None
    closed_at: datetime | None
    owner_id: int
    owner_name: str | None = None
    opportunity_id: int | None = None
    created_at: datetime | None
    updated_at: datetime | None
    created_by_id: int | None = None  # who added the lead (by hand or by an upload)
    created_by_name: str | None = None
    last_transferred_at: datetime | None = None  # when the lead last got a new owner (shown in the list)
    last_transferred_to: str | None = None  # and to whom
    # email campaigns: left out of every campaign while either is set
    email_invalid_at: datetime | None = None
    email_invalid_reason: str | None = None
    unsubscribed_at: datetime | None = None

    @field_serializer("annual_revenue")
    def _revenue(self, value):
        return money(value)


class LeadTransferOut(Out):
    id: int
    from_user_id: int | None
    from_user_name: str | None = None
    to_user_id: int
    to_user_name: str | None = None
    transferred_by_id: int
    transferred_by_name: str | None = None
    note: str | None
    transferred_at: datetime | None


class LeadDetail(LeadOut):
    """Everything the lead record page needs in one call."""

    tasks: list[TaskOut] = []
    notes: list[NoteOut] = []
    history: list[StageHistoryOut] = []
    transfers: list[LeadTransferOut] = []


class LeadTransfer(BaseModel):
    """Give the lead to another user. Only the owner changes: details and stage stay as they are."""
    to_user_id: int
    note: str | None = Field(None, max_length=300)


class TransferRequestCreate(BaseModel):
    """Ask for someone else's lead (the owner, their Manager or the Admin must approve)."""
    reason: str = Field(..., min_length=3, max_length=300)


class TransferRequestDecision(BaseModel):
    note: str | None = Field(None, max_length=300)  # required to reject


class BulkLeads(BaseModel):
    lead_ids: list[int] = Field(..., min_length=1, max_length=500)


class BulkTransfer(BulkLeads):
    to_user_id: int
    note: str | None = Field(None, max_length=300)


class BulkOpportunities(BaseModel):
    opportunity_ids: list[int] = Field(..., min_length=1, max_length=500)


class BulkOpportunityTransfer(BulkOpportunities):
    to_user_id: int
    note: str | None = Field(None, max_length=300)


class CancelDemo(BaseModel):
    """reschedule_to set: the demo moves to that date and the lead stays at Demo.
    Not set: the demo is cancelled and the lead goes back to Nurturing; that is a stage change, so the reason and a
    new task are required then (see leads.cancel_demo)."""
    reason: str | None = Field(None, max_length=300)
    reschedule_to: datetime | None = None
    task: "StageTask | None" = None  # defined below with the other stage-change rules


# ---------- Stage changes: every one needs the user's note (saved in the stage history) ----------

STAGE_NOTE_REQUIRED = "Enter a note to change the stage."
CONVERSION_COMMENT_REQUIRED = "Enter a conversion comment."  # the same note, on Convert (the "Conversion Comment")


def required_note(value, message: str = STAGE_NOTE_REQUIRED) -> str:
    """The user's own note for a stage change: text that isn't blank. Spaces and line breaks around it are trimmed;
    the formatting inside is kept."""
    if value is not None and not isinstance(value, str):
        raise PydanticCustomError("stage_note_type", "The note must be text.")
    value = (value or "").strip()
    if not value:
        raise PydanticCustomError("stage_note_required", message)
    return value


def stage_note(value) -> str:
    return required_note(value)


def conversion_comment(value) -> str:
    return required_note(value, CONVERSION_COMMENT_REQUIRED)


StageNote = Annotated[str, BeforeValidator(stage_note)]  # required: missing, null, "" and "   " are refused
ConversionComment = Annotated[str, BeforeValidator(conversion_comment)]  # the same rule, with its own message

# Every stage change except Lost also needs a new task: the follow-up the user plans (on Won, the post-sale task)

STAGE_TASK_REQUIRED = "Add a new task for this stage change."
TASK_SUBJECT_REQUIRED = "Enter a task subject."
TASK_DUE_REQUIRED = "Choose a due date for the task."


def task_subject(value) -> str:
    if value is not None and not isinstance(value, str):
        raise PydanticCustomError("task_subject_type", "The task subject must be text.")
    value = (value or "").strip()
    if not value:
        raise PydanticCustomError("task_subject_required", TASK_SUBJECT_REQUIRED)
    if len(value) > 200:
        raise PydanticCustomError("task_subject_length", "The task subject can be up to 200 characters.")
    return value


def task_due(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PydanticCustomError("task_due_required", TASK_DUE_REQUIRED)
    return value  # then read as a date and time, like the due date of any task


class StageTask(BaseModel):
    """The New Task of a stage change: the fields and rules of a new task (TaskCreate). The server links it to the
    record (on Convert, the new opportunity) and gives it to the record's owner unless another assignee is chosen
    (only by users who may assign records to others, as in POST /tasks)."""

    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, BeforeValidator(task_subject)]
    due_date: Annotated[datetime, BeforeValidator(task_due)]
    reminder_at: datetime | None = None
    priority: Priority = "Normal"
    description: str | None = None
    owner_id: int | None = None  # default: the owner of the record (the new opportunity on Convert)

    @model_validator(mode="before")
    @classmethod
    def _fields_left_out(cls, data):
        return {"title": None, "due_date": None, **data} if isinstance(data, dict) else data


CancelDemo.model_rebuild()


def stage_task(value):
    if value is None:
        raise PydanticCustomError("stage_task_required", STAGE_TASK_REQUIRED)
    return value


class NeedsTask(BaseModel):
    """A stage change that needs the user's new task (all but Lost)."""

    task: Annotated[StageTask, BeforeValidator(stage_task)]

    @model_validator(mode="before")
    @classmethod
    def _task_left_out(cls, data):
        return {**data, "task": None} if isinstance(data, dict) and "task" not in data else data


class LeadStageChange(NeedsTask):
    stage: LeadOpenStage
    demo_date: datetime | None = None  # used when moving to Demo: the demo task is due then
    # moving to Revisit: when to come back to the lead (the new task is due then) and why
    revisit_date: datetime | None = None
    revisit_reason: RevisitReason | None = None
    note: StageNote
    changed_by_id: int | None = None  # default: the lead owner
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"


class MarkUnqualified(BaseModel):
    """Close the lead as not eligible. The reason is required; notes say why (internal)."""
    reason: UnqualifiedReason
    notes: StageNote


class ReopenLead(NeedsTask):
    """Bring an Unqualified lead back (Salesforce "recycle"): it goes to New with the user's new task."""
    note: StageNote


class BulkOpportunityLost(BulkOpportunities):
    lost_reason: LostReason
    lost_notes: StageNote


class MarkLost(BaseModel):
    lost_reason: LostReason
    lost_notes: StageNote  # the note for this stage change; internal: never sent to the customer
    changed_by_id: int | None = None


class ConvertLead(NeedsTask):
    """The note (the Conversion Comment) and a new task for the new opportunity are required. account_id = attach to
    an existing account instead of creating one."""

    note: ConversionComment  # why the lead is converted: saved in the lead's and the new opportunity's stage history
    opportunity_name: str | None = Field(None, max_length=200)
    expected_value: float | None = Field(None, ge=0)
    currency: Currency | None = None  # default: the lead's currency
    expected_close_date: date | None = None
    account_id: int | None = None
    changed_by_id: int | None = None
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"

    @model_validator(mode="before")
    @classmethod
    def _comment_left_out(cls, data):
        """A request without the comment gets "Enter a conversion comment." too (not just "Field required")."""
        return {**data, "note": None} if isinstance(data, dict) and "note" not in data else data


# ---------- Accounts and contacts ----------

class AccountOut(Out):
    id: int
    name: str
    industry: str | None
    phone: str | None
    website: str | None
    address: str | None
    linkedin_url: str | None = None
    annual_revenue: Decimal | None = None
    currency: str = "USD"
    employees: int | None = None
    owner_id: int
    owner_name: str | None = None
    created_at: datetime | None
    updated_at: datetime | None = None
    last_activity_at: datetime | None = None  # the latest change on the account, its contacts, deals, tasks or emails
    activity: str | None = None  # lists: "upcoming" | "past" | "none" (Home's Accounts card pills, services.activity_of)

    @field_serializer("annual_revenue")
    def _revenue(self, value):
        return money(value)


# New Account / New Contact (and the Assistant's tools for them), and New Opportunity's new contact, need these filled
# in. Lead conversion and imports build accounts and contacts themselves, and older records may have them empty.
ACCOUNT_NAME_REQUIRED = "Enter the account name."
ACCOUNT_INDUSTRY_REQUIRED = "Enter the account's industry."
CONTACT_FIRST_NAME_REQUIRED = "Enter the contact's first name."
CONTACT_LAST_NAME_REQUIRED = "Enter the contact's last name."
CONTACT_EMAIL_REQUIRED = "Enter the contact's email address."
CONTACT_EMAIL_INVALID = "Enter a valid email address, like name@company.com."
# The contact's phone is optional; a given one is checked against the numbering rules of its country (Google's
# libphonenumber, the same rules as the form's libphonenumber-js) and saved in international format (+91 98765 43210).
# This checks the format only: it doesn't show that the number exists or belongs to the contact.
DEFAULT_PHONE_COUNTRY = "IN"  # India (+91), the form's default
PHONE_CHARACTERS = re.compile(r"\+?[0-9 ().\-]+")  # digits, spaces, brackets, hyphens, dots; an optional leading +
PHONE_WITH_CODE_INVALID = "Enter a valid phone number, including its country code after the +."


def phone_country_label(region: str) -> str:
    """'IN' -> 'India (+91)': the name and calling code, as the form's country list shows them."""
    import phonenumbers
    from phonenumbers import geocoder

    example = phonenumbers.example_number(region)
    name = geocoder.country_name_for_number(example, "en") if example else ""
    return f"{name or region} (+{phonenumbers.country_code_for_region(region)})"


def international_phone(value, country: str | None) -> str | None:
    """A contact's phone number checked for its country, in international format ("" or only spaces -> None).
    Without a leading +, the number must be valid in the chosen country; with one, its own country code decides."""
    import phonenumbers

    if value is not None and not isinstance(value, str):
        raise PydanticCustomError("phone_type", "Enter the phone number as text.")
    text = (value or "").strip()
    if not text:
        return None
    region = (country or DEFAULT_PHONE_COUNTRY).strip().upper()
    if region not in phonenumbers.SUPPORTED_REGIONS:
        raise PydanticCustomError("phone_country", "Choose the phone number's country.")
    message = PHONE_WITH_CODE_INVALID if text.startswith("+") else f"Enter a valid phone number for {phone_country_label(region)}."
    if not PHONE_CHARACTERS.fullmatch(text):
        raise PydanticCustomError("phone_invalid", message)
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        raise PydanticCustomError("phone_invalid", message) from None
    valid = (phonenumbers.is_valid_number(number) if text.startswith("+")
             else phonenumbers.is_valid_number_for_region(number, region))
    if not valid:
        raise PydanticCustomError("phone_invalid", message)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def valid_international_phone(value) -> str | None:
    """A phone number that carries its country code and is valid for it, in international format; otherwise None.
    For numbers from outside the form (Apollo): one without +country, or malformed, is never used."""
    import phonenumbers

    text = value.strip() if isinstance(value, str) else ""
    if not text.startswith("+") or not PHONE_CHARACTERS.fullmatch(text):
        return None
    try:
        number = phonenumbers.parse(text, None)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL) \
        if phonenumbers.is_valid_number(number) else None


def contact_linkedin(value) -> str | None:
    """A contact's own LinkedIn profile (optional), saved in one form: https://linkedin.com/in/<name>."""
    text = trimmed(value)
    if not text:
        return None
    try:
        return linkedin_profile_url(text)
    except ValueError as error:
        raise PydanticCustomError("linkedin_profile", str(error)) from None


def web_address(value, *, linkedin: bool = False) -> str | None:
    """An optional web address, checked like the lead form's (clean_url); "" -> None."""
    try:
        return clean_url(value, linkedin=linkedin)
    except ValueError as error:
        raise PydanticCustomError("web_address", str(error)) from None


def required_text(value, message: str) -> str:
    """A field that must be filled in: missing, null, empty and whitespace-only values get `message`. Spaces around
    the value are trimmed; the value itself is kept as typed (no phone format is imposed)."""
    if value is not None and not isinstance(value, str):
        raise PydanticCustomError("required_text_type", "Enter text.")
    value = (value or "").strip()
    if not value:
        raise PydanticCustomError("required_text", message)
    return value


def contact_email(value) -> str:
    from app.services import CUSTOMER_EMAIL_RE  # the app's one email format check (also used by the Apollo lookup)

    value = required_text(value, CONTACT_EMAIL_REQUIRED)
    if not CUSTOMER_EMAIL_RE.match(value):
        raise PydanticCustomError("contact_email_invalid", CONTACT_EMAIL_INVALID)
    return value


AccountName = Annotated[str, BeforeValidator(lambda v: required_text(v, ACCOUNT_NAME_REQUIRED))]
AccountIndustry = Annotated[str, BeforeValidator(lambda v: required_text(v, ACCOUNT_INDUSTRY_REQUIRED))]
ContactFirstName = Annotated[str, BeforeValidator(lambda v: required_text(v, CONTACT_FIRST_NAME_REQUIRED))]
ContactLastName = Annotated[str, BeforeValidator(lambda v: required_text(v, CONTACT_LAST_NAME_REQUIRED))]
ContactEmail = Annotated[str, BeforeValidator(contact_email)]
ContactLinkedIn = Annotated[str | None, BeforeValidator(contact_linkedin)]
Website = Annotated[str | None, BeforeValidator(web_address)]
CompanyLinkedIn = Annotated[str | None, BeforeValidator(lambda v: web_address(v, linkedin=True))]


class AccountCreate(BaseModel):
    """New Account: Account Name and Industry are required; Website and Company LinkedIn URL are optional (checked
    when given). There is no Phone on the form: a phone sent through the API is optional and kept as given."""

    name: AccountName = Field(..., max_length=200)
    industry: AccountIndustry = Field(..., max_length=100)
    phone: Annotated[str | None, BeforeValidator(trimmed)] = Field(None, max_length=30)
    website: Website = Field(None, max_length=255)
    linkedin_url: CompanyLinkedIn = Field(None, max_length=300)  # the company's LinkedIn page
    address: str | None = Field(None, max_length=500)
    owner_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _required_left_out(cls, data):
        """A request without a name or industry gets their own messages too (not just "Field required")."""
        return {"name": None, "industry": None, **data} if isinstance(data, dict) else data


class ContactOut(Out):
    id: int
    salutation: str | None
    first_name: str | None
    last_name: str
    full_name: str  # first + last name, filled automatically
    job_title: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None = None
    account_id: int
    account_name: str | None = None
    activity: str | None = None  # lists: "upcoming" | "past" | "none" (Home's Contacts card pills)
    owner_id: int
    created_at: datetime | None
    updated_at: datetime | None = None


class ContactCreate(BaseModel):
    """New Contact: First Name, Last Name, Email and the account are required. Phone is optional and checked for the
    chosen country (phone_country, default India); the LinkedIn Profile URL is optional (a person's profile)."""

    salutation: Salutation | None = None
    first_name: ContactFirstName = Field(..., max_length=50)
    last_name: ContactLastName = Field(..., max_length=50)
    job_title: str | None = Field(None, max_length=100)
    email: ContactEmail = Field(..., max_length=255)
    phone_country: str = Field(DEFAULT_PHONE_COUNTRY, min_length=2, max_length=2)  # not saved: the number says it
    phone: str | None = Field(None, max_length=30)
    linkedin_url: ContactLinkedIn = Field(None, max_length=300)
    account_id: int
    owner_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _required_left_out(cls, data):
        """A request without a name or email gets their own messages too (not just "Field required")."""
        return {"first_name": None, "last_name": None, "email": None, **data} if isinstance(data, dict) else data

    @field_validator("phone_country")
    @classmethod
    def _country(cls, value):
        import phonenumbers

        if value.upper() not in phonenumbers.SUPPORTED_REGIONS:
            raise PydanticCustomError("phone_country", "Choose the phone number's country.")
        return value.upper()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value, info):
        if "phone_country" not in info.data and (value or "").strip():  # an invalid country: never assume India
            raise PydanticCustomError("phone_country", "Choose the phone number's country.")
        return international_phone(value, info.data.get("phone_country"))


# ---------- Opportunities ----------

class OpportunityOut(Out):
    id: int
    name: str
    stage: str
    expected_value: float | None
    final_value: float | None
    currency: str = "USD"
    expected_close_date: date | None
    probability: int
    lost_reason: str | None
    lost_notes: str | None
    discovery_needs: str | None = None
    discovery_budget: str | None = None
    discovery_decision_maker: str | None = None
    discovery_timeline: str | None = None
    closed_at: datetime | None
    account_id: int
    account_name: str | None = None
    primary_contact_id: int | None
    primary_contact_name: str | None = None
    lead_id: int | None
    lead_name: str | None = None
    owner_id: int
    owner_name: str | None = None
    created_at: datetime | None
    updated_at: datetime | None

    @field_serializer("expected_value", "final_value")
    def _money(self, value):
        return money(value)


class AccountDetail(AccountOut):
    contacts: list[ContactOut] = []
    opportunities: list[OpportunityOut] = []


class OpportunityDetail(OpportunityOut):
    tasks: list[TaskOut] = []
    notes: list[NoteOut] = []
    history: list[StageHistoryOut] = []


class OpportunityUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    expected_value: float | None = Field(None, ge=0)
    currency: Currency | None = None
    expected_close_date: date | None = None
    probability: int | None = Field(None, ge=0, le=100)  # set automatically by stage; can be adjusted
    primary_contact_id: int | None = None
    owner_id: int | None = None
    changed_by_id: int | None = None  # logged-in user (not saved; used for the assignment notification)
    discovery_needs: str | None = Field(None, max_length=2000)
    discovery_budget: str | None = Field(None, max_length=100)
    discovery_decision_maker: str | None = Field(None, max_length=150)
    discovery_timeline: str | None = Field(None, max_length=100)


class OpportunityCreate(NeedsTask):
    """New Opportunity (Opportunities or Account page), without a lead. The account is an existing one (account_id) or
    a company name (an existing account with that name is reused). The contact is an existing one on that account
    (primary_contact_id) or a person (an existing contact with that email or name is reused). The note and the first
    task are required, like on Convert."""

    name: str = Field(..., min_length=1, max_length=200)
    note: StageNote  # why the opportunity is opened: saved in its stage history
    expected_value: float | None = Field(None, ge=0)
    currency: Currency | None = None  # default: the account's currency
    expected_close_date: date | None = None
    owner_id: int | None = None  # default: the logged-in user
    account_id: int | None = None
    account_name: str | None = Field(None, max_length=200)
    primary_contact_id: int | None = None
    # a new contact (no primary_contact_id): the same fields and rules as New Contact
    contact_salutation: Salutation | None = None
    contact_first_name: str | None = Field(None, max_length=50)
    contact_last_name: str | None = Field(None, max_length=50)
    contact_email: str | None = Field(None, max_length=255)
    contact_title: str | None = Field(None, max_length=100)
    contact_phone_country: str = Field(DEFAULT_PHONE_COUNTRY, min_length=2, max_length=2)  # not saved
    contact_phone: str | None = Field(None, max_length=30)
    contact_linkedin_url: str | None = Field(None, max_length=300)

    @model_validator(mode="after")
    def _account_and_contact(self):
        if self.account_id is None and not (self.account_name or "").strip():
            raise ValueError("Choose an account or enter the company name")
        if self.primary_contact_id is not None:
            return self  # an existing contact is reused as it is: no new contact fields are needed or checked
        self.contact_first_name = required_text(self.contact_first_name, CONTACT_FIRST_NAME_REQUIRED)
        self.contact_last_name = required_text(self.contact_last_name, CONTACT_LAST_NAME_REQUIRED)
        self.contact_email = contact_email(self.contact_email)
        self.contact_phone = international_phone(self.contact_phone, self.contact_phone_country)
        self.contact_linkedin_url = contact_linkedin(self.contact_linkedin_url)
        return self


class OpportunityCreated(BaseModel):
    opportunity: OpportunityOut
    account: AccountOut
    contact: ContactOut
    new_task: TaskOut | None
    reused: dict[str, bool]


class OpportunityStageChange(NeedsTask):
    stage: OpportunityOpenStage
    note: StageNote
    # moving to Discovery (Salesforce "Needs Analysis"): what the customer needs is required, the rest optional
    discovery_needs: str | None = Field(None, max_length=2000)
    discovery_budget: str | None = Field(None, max_length=100)
    discovery_decision_maker: str | None = Field(None, max_length=150)
    discovery_timeline: str | None = Field(None, max_length=100)
    changed_by_id: int | None = None
    completed_stages: list[str] = []  # stages skipped on the way (e.g. Discovery), confirmed as already done
    completed_note: str | None = Field(None, max_length=500)


class MarkWon(NeedsTask):
    """task: the post-sale task (e.g. handover or onboarding); it stays open on the won deal."""
    final_value: float | None = Field(None, ge=0)  # default: the expected value
    note: StageNote  # the closing note
    changed_by_id: int | None = None
    completed_stages: list[str] = []  # stages skipped on the way, confirmed as already done by the salesperson
    completed_note: str | None = Field(None, max_length=500)  # e.g. "Demo was done on a call"


class ConvertResult(BaseModel):
    lead: LeadOut
    account: AccountOut
    contact: ContactOut
    opportunity: OpportunityOut
    tasks_auto_closed: int
    new_task: TaskOut | None
    reused: dict[str, bool] = {}  # {"account": True} = the company's existing account was used (no duplicate)


# ---------- Notifications and search ----------

class NotificationOut(Out):
    id: int
    user_id: int
    task_id: int | None
    title: str
    message: str | None
    link: str | None = None
    kind: str = "update"  # "update" (vanishes once seen) or "reminder" (stays until the task is done)
    is_read: bool
    created_at: datetime | None


# ---------- Emails ----------

class AttachmentOut(Out):
    id: int
    filename: str
    content_type: str
    size_bytes: int


class EmailOut(Out):
    id: int
    subject: str
    body: str
    to_address: str
    cc_address: str | None
    status: str
    error: str | None
    sent_by_id: int
    sent_by_name: str | None = None
    lead_id: int | None
    opportunity_id: int | None
    contact_id: int | None
    account_id: int | None
    sent_at: datetime | None
    attachments: list[AttachmentOut] = []


class OpportunityAttachmentOut(Out):
    """A file on an opportunity (never the bytes: those come from the download only)."""
    id: int
    opportunity_id: int
    filename: str
    content_type: str  # detected from the file content by the server
    size_bytes: int
    stage: str  # stage of the deal when the file was uploaded
    uploaded_by_id: int
    uploaded_by_name: str | None = None
    uploaded_at: datetime | None


class SearchResult(BaseModel):
    type: str
    id: int
    name: str
    detail: str | None
