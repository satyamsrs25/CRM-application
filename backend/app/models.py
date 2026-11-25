"""Python classes that map to the PostgreSQL tables in database/schema.sql.
The tables are created by the SQL script; these classes only read/write them.
(server_default=func.now() mirrors DEFAULT CURRENT_TIMESTAMP in the SQL, so tests on SQLite behave the same.)"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Computed, DateTime, ForeignKey, LargeBinary, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="Salesperson")
    is_active: Mapped[bool] = mapped_column(default=True)
    # Which notifications also come by email (the bell always shows everything). Changed in My Profile.
    email_stage_updates: Mapped[bool] = mapped_column(default=False)   # lead / deal moved to the next stage
    email_assignments: Mapped[bool] = mapped_column(default=True)      # a record was assigned to me
    email_reminders: Mapped[bool] = mapped_column(default=True)        # task, demo, close-date, overdue reminders
    team_access: Mapped[bool] = mapped_column(default=False)           # a Manager let this user see the team's records
    role_changed_at: Mapped[datetime | None]    # last time the Admin changed the role
    access_changed_at: Mapped[datetime | None]  # last activate / deactivate / team access change
    # A Salesperson's Manager: the Manager adds and deactivates the people in their team and sees their activity
    reports_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    reports_to: Mapped["User | None"] = relationship(remote_side=[id])

    @property
    def reports_to_name(self) -> str | None:
        return self.reports_to.full_name if self.reports_to else None


class ActivityLog(Base):
    """Admin activity log: who changed users, permissions and record owners, and when."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    actor: Mapped[User | None] = relationship()


class RolePermission(Base):
    """What the Admin changed on the Roles & Permissions page (the defaults live in app/security.py)."""

    __tablename__ = "role_permissions"

    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    permission: Mapped[str] = mapped_column(String(40), primary_key=True)
    allowed: Mapped[bool]
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    updated_by: Mapped[User | None] = relationship()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30))
    website: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    annual_revenue: Mapped[Decimal | None]
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")  # of the turnover
    employees: Mapped[int | None]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    salutation: Mapped[str | None] = mapped_column(String(10))
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    # filled automatically by the database from first + last name
    full_name: Mapped[str] = mapped_column(String(101), Computed("TRIM(COALESCE(first_name || ' ', '') || last_name)", persisted=True))
    job_title: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    # Region: the country chosen beside the phone (two-letter code, e.g. IN, US, CA); empty when nobody chose one
    phone_country: Mapped[str | None] = mapped_column(String(2))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    account: Mapped[Account] = relationship(back_populates="contacts")
    owner: Mapped[User] = relationship()


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    salutation: Mapped[str | None] = mapped_column(String(10))
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    # filled automatically by the database from first + last name
    name: Mapped[str] = mapped_column(String(101), Computed("TRIM(COALESCE(first_name || ' ', '') || last_name)", persisted=True))
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    # Region: the country chosen beside the phone (two-letter code); empty when nobody chose one (older leads too)
    phone_country: Mapped[str | None] = mapped_column(String(2))
    # research links and company size (shown as clickable links on the lead)
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    company_website: Mapped[str | None] = mapped_column(String(255))
    company_linkedin_url: Mapped[str | None] = mapped_column(String(300))
    annual_revenue: Mapped[Decimal | None]  # turnover, in the lead's currency
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")  # constants.CURRENCIES
    employees: Mapped[int | None]  # headcount
    location: Mapped[str | None] = mapped_column(String(200))
    # uploaded from a file and nobody has worked on it yet (kept out of the normal lists until someone does)
    untouched: Mapped[bool] = mapped_column(default=False, server_default="false")
    uploaded_from: Mapped[str | None] = mapped_column(String(255))  # file name, for leads created by an upload
    source: Mapped[str] = mapped_column(String(20), default="Other")
    source_detail: Mapped[str | None] = mapped_column(String(100))  # Lead Source Other: what the source is
    stage: Mapped[str] = mapped_column(String(20), default="New")   # constants.LEAD_STAGES
    demo_date: Mapped[datetime | None]
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_notes: Mapped[str | None] = mapped_column(Text)
    # Unqualified (not eligible): why, and notes. Revisit ("not now"): when to come back to the lead, and why.
    unqualified_reason: Mapped[str | None] = mapped_column(String(20))
    unqualified_notes: Mapped[str | None] = mapped_column(Text)
    revisit_date: Mapped[datetime | None]
    revisit_reason: Mapped[str | None] = mapped_column(String(30))
    converted_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    # no owner: the lead is in the Unassigned Pool (bulk uploads start there) until the Admin or a Manager assigns it
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime | None]  # when the current owner got it (empty: not recorded, e.g. older leads)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # who added the lead (by hand or upload)
    # Email campaigns: an address that doesn't work, and leads who unsubscribed, are left out of every campaign
    email_invalid_at: Mapped[datetime | None]
    email_invalid_reason: Mapped[str | None] = mapped_column(String(300))
    unsubscribed_at: Mapped[datetime | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    opportunity: Mapped["Opportunity | None"] = relationship(back_populates="lead")
    tasks: Mapped[list["Task"]] = relationship(back_populates="lead")
    history: Mapped[list["StageHistory"]] = relationship(back_populates="lead")
    notes: Mapped[list["Note"]] = relationship(back_populates="lead")
    transfers: Mapped[list["LeadTransfer"]] = relationship(back_populates="lead", order_by="LeadTransfer.id")


class LeadTransfer(Base):
    """Every time a lead gets a new owner: from whom, to whom, who did it and when."""

    __tablename__ = "lead_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transferred_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(300))
    transferred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # the approved request that gave the lead to its new owner (empty: a direct transfer or assignment)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("lead_transfer_requests.id", ondelete="SET NULL"))

    lead: Mapped[Lead] = relationship(back_populates="transfers")
    from_user: Mapped[User | None] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped[User] = relationship(foreign_keys=[to_user_id])
    transferred_by: Mapped[User] = relationship(foreign_keys=[transferred_by_id])


class AnalyticsChart(Base):
    """One chart on a user's Analytics board (Home > Analytics), built by the user: what to count (metric), how to
    split it (group_by), how to draw it (chart_type) and over which period. Their Manager and the Admin see it live."""

    __tablename__ = "analytics_charts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str] = mapped_column(String(30))       # app/routers/analytics.py METRICS
    group_by: Mapped[str] = mapped_column(String(20))     # app/routers/analytics.py GROUPS
    chart_type: Mapped[str] = mapped_column(String(10))   # bar, column, line, donut, number
    period: Mapped[str] = mapped_column(String(15))       # app/routers/analytics.py PERIODS (custom: start_date, end_date)
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")  # money metrics only
    width: Mapped[str] = mapped_column(String(10), default="half", server_default="half")  # quarter, half, full
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())


class AnalyticsReport(Base):
    """A dated snapshot of a user's Analytics charts (Send Report: the board; Share as Excel: one chart) with a note,
    sent to the people the user picked, who can mark it reviewed with an optional comment."""

    __tablename__ = "analytics_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    charts: Mapped[str] = mapped_column(Text)  # JSON: the charts with their numbers when it was sent
    kind: Mapped[str] = mapped_column(String(10), default="board")  # board (Send Report) or chart (Share as Excel)
    sent_to: Mapped[str | None] = mapped_column(String(300))  # who it went to, for the record ("Priya Sharma")
    recipient_ids: Mapped[str | None] = mapped_column(Text)  # ",3,7,": who it went to (older reports: none)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    review_comment: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])


class LeadTransferRequest(Base):
    """A user asks for someone else's lead. The lead's owner, the owner's Manager or the Admin approves or rejects it;
    the lead moves (a LeadTransfer) only when it is approved."""

    __tablename__ = "lead_transfer_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # gets the lead when approved
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # the owner when asked for (none: the pool)
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="Pending")  # Pending, Approved, Rejected, Cancelled
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(String(300))
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    lead: Mapped[Lead] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(20), default="Opportunity")   # constants.OPPORTUNITY_STAGES
    expected_value: Mapped[Decimal | None]
    final_value: Mapped[Decimal | None]
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")  # of both amounts
    expected_close_date: Mapped[date | None]
    probability: Mapped[int] = mapped_column(default=20)  # % chance to win, set by stage
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_notes: Mapped[str | None] = mapped_column(Text)
    # Discovery (Salesforce "Needs Analysis"): what the customer needs, budget, who decides, timeline
    discovery_needs: Mapped[str | None] = mapped_column(Text)
    discovery_budget: Mapped[str | None] = mapped_column(String(100))
    discovery_decision_maker: Mapped[str | None] = mapped_column(String(150))
    discovery_timeline: Mapped[str | None] = mapped_column(String(100))
    closed_at: Mapped[datetime | None]
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    primary_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    account: Mapped[Account] = relationship(back_populates="opportunities")
    primary_contact: Mapped[Contact | None] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="opportunity")
    owner: Mapped[User] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="opportunity")
    history: Mapped[list["StageHistory"]] = relationship(back_populates="opportunity")
    notes: Mapped[list["Note"]] = relationship(back_populates="opportunity")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime]
    reminder_at: Mapped[datetime | None]
    reminder_sent: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="Open")      # Open/Done/Auto-closed
    priority: Mapped[str] = mapped_column(String(10), default="Normal")  # Low/Normal/High
    is_auto: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="tasks")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="tasks")


class StageHistory(Base):
    __tablename__ = "stage_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))

    changed_by: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="history")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="history")


class DeletedLead(Base):
    """A copy of a deleted lead (Leads > Deleted Leads): every field of the lead and its notes, so the Admin or a
    Manager can restore it. Restoring puts it back in the Unassigned Pool and removes this copy."""
    __tablename__ = "deleted_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int]  # the lead's id (it gets it back when restored, if still free)
    name: Mapped[str] = mapped_column(String(101))
    company: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str | None] = mapped_column(String(20))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # its owner when it was deleted
    owner_name: Mapped[str | None] = mapped_column(String(100))
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    data: Mapped[str] = mapped_column(Text)  # JSON: {"lead": {column: value}, "notes": [{body, created_by_id, created_at}]}

    deleted_by: Mapped[User | None] = relationship(foreign_keys=[deleted_by_id])


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    created_by: Mapped[User] = relationship()
    lead: Mapped[Lead | None] = relationship(back_populates="notes")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="notes")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(200))  # page in the app, e.g. /leads/5
    kind: Mapped[str] = mapped_column(String(10), default="update")  # update | reminder
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship()
    task: Mapped[Task | None] = relationship()

class Email(Base):
    """An email sent from the CRM to a lead / contact, saved on the record's activity."""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    to_address: Mapped[str] = mapped_column(String(500))
    cc_address: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="Sent")  # Sent / Failed
    error: Mapped[str | None] = mapped_column(Text)
    sent_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    sent_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    sent_by: Mapped[User] = relationship()
    attachments: Mapped[list["EmailAttachment"]] = relationship(back_populates="email", cascade="all, delete-orphan")


class EmailAttachment(Base):
    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary)

    email: Mapped[Email] = relationship(back_populates="attachments")


class OpportunityAttachment(Base):
    """A file kept on an opportunity (proposal, quote, signed order...), uploaded at the Opportunity or Proposal stage.
    The bytes are deferred: lists and other queries never load them, only the download does.
    Deleting only hides the file (deleted_at / deleted_by_id are set); the row and the bytes stay."""

    __tablename__ = "opportunity_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"))
    stage: Mapped[str] = mapped_column(String(20))           # stage of the deal when the file was uploaded
    filename: Mapped[str] = mapped_column(String(255))       # cleaned name shown in the app
    content_type: Mapped[str] = mapped_column(String(100))   # detected from the file content by the server
    size_bytes: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    opportunity: Mapped[Opportunity] = relationship()
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])
    deleted_by: Mapped[User | None] = relationship(foreign_keys=[deleted_by_id])


class Campaign(Base):
    """One email sent to many leads (Leads > select > Email, or Campaigns > New Campaign).
    Sent a few at a time by app/campaigns.py so the Outlook mailbox stays under its sending limits."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    cc: Mapped[str | None] = mapped_column(String(1000))                  # copied on every email ("a@x.com, b@y.com")
    status: Mapped[str] = mapped_column(String(15), default="Scheduled")  # Scheduled, Sending, Paused, Completed, Cancelled
    status_note: Mapped[str | None] = mapped_column(String(300))           # why it was paused, etc.
    send_at: Mapped[datetime]                                              # when sending starts
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # open / click tracking chosen on New Campaign (off unless asked, and only while the Admin allows tracking:
    # app/tracking.py). Campaigns made before tracking existed keep both off.
    track_opens: Mapped[bool] = mapped_column(default=False, server_default=false())
    track_clicks: Mapped[bool] = mapped_column(default=False, server_default=false())

    created_by: Mapped[User] = relationship()
    recipients: Mapped[list["CampaignRecipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class CampaignRecipient(Base):
    """One lead in a campaign. Queued -> Sent, or Failed (after retries), Invalid (the address doesn't work),
    Skipped (unsubscribed / invalid / no email when the campaign was made or before its turn), Cancelled."""

    __tablename__ = "campaign_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    email: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(101))
    company: Mapped[str | None] = mapped_column(String(200))   # for {company} when the email was typed in
    manual: Mapped[bool] = mapped_column(default=False)        # typed in (not a lead in the CRM)
    status: Mapped[str] = mapped_column(String(10), default="Queued")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(String(300))
    # tracking (app/tracking.py): a random token for this email's tracking links (never the email or the lead id),
    # whether the sent email carried an open image / tracked links, and the signals so far (UTC). Engagement is kept
    # apart from the sending status: a signal never makes an email "Delivered".
    tracking_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    opens_tracked: Mapped[bool] = mapped_column(default=False, server_default=false())
    clicks_tracked: Mapped[bool] = mapped_column(default=False, server_default=false())
    first_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_events: Mapped[int] = mapped_column(default=0, server_default="0")
    first_click_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_click_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    click_events: Mapped[int] = mapped_column(default=0, server_default="0")

    campaign: Mapped[Campaign] = relationship(back_populates="recipients")


class CampaignLink(Base):
    """A link in a campaign's message that clicks are tracked on: the original address (checked: http or https, no
    user name or password) and the random key in its tracking address. A click always goes to this stored address:
    nothing in the tracking address can send people anywhere else."""

    __tablename__ = "campaign_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    link_key: Mapped[str] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignEvent(Base):
    """One open or click signal (kept TRACKING_RETENTION_DAYS, then deleted: app/tracking.py). Only the time (UTC),
    the link and a cautious "possibly automated" hint are kept: no address, browser details or location."""

    __tablename__ = "campaign_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("campaign_recipients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(5))  # open | click
    link_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_links.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    automated_hint: Mapped[str | None] = mapped_column(String(60))


class AppSetting(Base):
    """A setting the Admin changes in the app (e.g. email_tracking_enabled). No row: the default (off)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailAddress(Base):
    """Campaign email state of one address, lead or not: unsubscribed, or doesn't work. Typed-in addresses (people not
    in the CRM) are only tracked here; a lead with the same email is kept in step (leads.unsubscribed_at...)."""

    __tablename__ = "email_addresses"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)  # lower case
    subscribed_at: Mapped[datetime | None]      # clicked Subscribe: emails then carry only the Unsubscribe link
    unsubscribed_at: Mapped[datetime | None]
    invalid_at: Mapped[datetime | None]
    invalid_reason: Mapped[str | None] = mapped_column(String(300))


class AssistantConversation(Base):
    """One AI Assistant chat, kept for its user (the history panel). messages: the conversation in the AI's format;
    chat: what the page shows (bubbles, links, suggestions); pending: the action waiting for Confirm, if any."""

    __tablename__ = "assistant_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    messages: Mapped[str] = mapped_column(Text, default="[]")   # JSON
    chat: Mapped[str] = mapped_column(Text, default="[]")       # JSON
    pending: Mapped[str | None] = mapped_column(Text)           # JSON
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())


class AssistantFile(Base):
    """A file attached in the AI Assistant chat. Text is read out of documents when uploaded (the AI reads the text);
    images are kept so the AI can look at them. The bytes are deferred: lists never load them."""

    __tablename__ = "assistant_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10))               # "text" or "image"
    size_bytes: Mapped[int]
    text: Mapped[str | None] = mapped_column(Text)              # the readable text (documents)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)  # images only
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())


class SavedView(Base):
    """A user's own named list view (the Opportunities list for now): the built-in view it starts from, its filters, search
    and sort. Only its owner lists, renames or deletes it. It never widens what anyone sees: the records always come from
    the permission-checked list, and the owners it names are checked again against the user's access when it is read."""

    __tablename__ = "saved_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    collection: Mapped[str] = mapped_column(String(20))   # "opportunities"
    name: Mapped[str] = mapped_column(String(60))
    base_view: Mapped[str] = mapped_column(String(60))    # a built-in view ("My Open Opportunities"): its scope stays
    filters: Mapped[str] = mapped_column(Text)            # JSON: {"owner": "2,7", "close": "month", ...} (choices, not dates)
    search: Mapped[str | None] = mapped_column(String(100))
    sort: Mapped[str | None] = mapped_column(Text)        # JSON: {"column": "Amount", "dir": -1}
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())
