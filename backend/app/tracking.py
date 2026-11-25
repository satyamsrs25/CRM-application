"""Open and click tracking for campaign emails that SalesTrack sends itself (Email Campaigns). Nothing else is tracked:
not Open in Outlook drafts, not notifications or reports, not the app's own links (issue 1's Open in SalesTrack).

Off by default, twice over:
- the Admin allows tracking (Email Campaigns > Tracking settings: app_settings.email_tracking_enabled, no row = off);
- each campaign asks for it on New Campaign: Track opens and/or Track clicks (campaigns made before stay off).
Turning it off stops collecting at once (no new image or tracked links in emails sent from then on, and no new signals
recorded); links in emails already sent keep taking people to where they lead.

What it does, for an email sent while both allow it:
- opens: a transparent 1x1 image with this email's own random token (the HTML version only);
- clicks: each http(s) link in the message becomes a tracking address with the same token and the link's random key;
  it records the click and sends the person on to the stored original address (never one given in the request).
  Not tracked: the Unsubscribe / Subscribe links, the app's own links (sign-in, records, assignments), mailto: and tel:.
No email address or lead id is in a tracking address. Signals are times (UTC) only, with a cautious "possibly
automated" hint; no IP address, browser details or location are kept. Signals are deleted after
TRACKING_RETENTION_DAYS (default 90); the per-recipient totals stay with the campaign.

What a signal means: an image or a link was requested. Mail apps and security scanners load images and follow links
on their own (Apple Mail Privacy Protection, link scanners, previews), some mail apps never load images, and a
forwarded email records the forwarder's reader against the original recipient. So "opened" is "an open signal",
"no open detected" is not "unread", and nothing here proves reading. Signals never change a lead (priority, owner,
follow-ups) and never count as delivery.
"""
import base64
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app import mailer
from app.models import AppSetting, CampaignEvent, CampaignLink, CampaignRecipient, User

log = logging.getLogger("crm.tracking")

SETTING = "email_tracking_enabled"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
MAX_URL = 2000
# 1x1 transparent GIF
PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, private", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer"}
# browser details that show a program rather than a person (checked, never stored). A cautious hint only: most
# automated requests can't be told apart (an image proxy or a scanner can look like any browser)
AUTOMATED_WORDS = ("bot", "spider", "crawler", "scanner", "python-requests", "python-urllib", "curl/", "wget",
                   "headless", "go-http-client", "java/", "libwww", "okhttp", "proofpoint", "mimecast", "barracuda",
                   "safelinks", "linkchecker")
SOON_AFTER_SENDING = timedelta(seconds=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def as_utc(value: datetime | None) -> datetime | None:
    """A stored tracking time as UTC (PostgreSQL returns it with its zone; the SQLite test database without)."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat().replace("+00:00", "Z") if value else None


# ---------- the Admin's setting ----------

def enabled(db: Session) -> bool:
    row = db.get(AppSetting, SETTING)
    return bool(row and row.value == "true")


def set_enabled(db: Session, value: bool, user_id: int) -> None:
    row = db.get(AppSetting, SETTING) or AppSetting(key=SETTING)
    row.value, row.updated_by_id, row.updated_at = ("true" if value else "false"), user_id, utcnow()
    db.add(row)


def retention_days() -> int:
    """How long signals are kept (TRACKING_RETENTION_DAYS, default 90, between 1 and 730)."""
    try:
        days = int(os.getenv("TRACKING_RETENTION_DAYS", "90"))
    except ValueError:
        days = 90
    return min(max(days, 1), 730)


def public_base() -> str:
    """Where tracking addresses point: PUBLIC_URL, else APP_URL (as the Unsubscribe links)."""
    return os.getenv("PUBLIC_URL", "").rstrip("/") or mailer.settings()["app_url"]


def reachable(base: str) -> bool:
    """Can people outside open it? localhost and private addresses only work for local tests; https is needed."""
    return base.startswith("https://") and not re.search(
        r"//(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[::1\])", base)


def settings_out(db: Session) -> dict:
    row = db.get(AppSetting, SETTING)
    who = db.get(User, row.updated_by_id) if row and row.updated_by_id else None
    base = public_base()
    return {"enabled": enabled(db), "updated_by": who.full_name if who else None,
            "updated_at": iso(row.updated_at) if row else None, "retention_days": retention_days(),
            "tracking_base": base, "public_https": reachable(base)}


# ---------- the email: tracking addresses ----------

def new_token() -> str:
    return secrets.token_urlsafe(24)  # 32 characters, random


def ensure_token(row: CampaignRecipient) -> str:
    if not row.tracking_token:
        row.tracking_token = new_token()
    return row.tracking_token


def open_url(token: str) -> str:
    return f"{public_base()}/api/public/t/o/{token}.gif"


def click_url(token: str, key: str) -> str:
    return f"{public_base()}/api/public/t/c/{token}/{key}"


def find_urls(text: str) -> list[tuple[int, int, str]]:
    """(start, end, url) of each http(s) address in the text, without trailing punctuation ("see https://x.com.")."""
    found = []
    for m in URL_RE.finditer(text or ""):
        url = m.group(0)
        while url and url[-1] in ".,;:!?'\"]}>":
            url = url[:-1]
        if url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        if len(url) > len("https://"):
            found.append((m.start(), m.start() + len(url), url))
    return found


def _place(url: str) -> tuple[str, int] | None:
    parts = urlsplit(url)
    if not parts.hostname:
        return None
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    return parts.hostname.lower(), port


def eligible(url: str) -> bool:
    """A content link whose clicks may be tracked: http(s), a host, no user name or password, not too long, and not
    one of the app's own addresses (sign-in, records, assignments, Unsubscribe / Subscribe)."""
    if len(url) > MAX_URL:
        return False
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return False
    place = _place(url)
    own = {_place(public_base()), _place(mailer.settings()["app_url"])}
    return place is not None and place not in own


def link_for(db: Session, campaign_id: int, url: str) -> CampaignLink:
    """The campaign's stored link for this address (one per address, however often it appears or is sent)."""
    link = db.scalar(select(CampaignLink).where(CampaignLink.campaign_id == campaign_id, CampaignLink.url == url))
    if link is None:
        link = CampaignLink(campaign_id=campaign_id, url=url, link_key=secrets.token_urlsafe(9))
        db.add(link)
        db.flush()
    return link


def tracked_links(db: Session, row: CampaignRecipient, text: str) -> dict[str, str]:
    """original address -> this email's tracking address, for the eligible links in the (filled-in) message."""
    token = ensure_token(row)
    out = {}
    for _, _, url in find_urls(text):
        if url not in out and eligible(url):
            out[url] = click_url(token, link_for(db, row.campaign_id, url).link_key)
    return out


def rewrite_text(text: str, links: dict[str, str]) -> str:
    """The plain-text version: each tracked link replaced by its tracking address (the others stay as written)."""
    if not links:
        return text
    out, last = [], 0
    for start, end, url in find_urls(text):
        out.append(text[last:start])
        out.append(links.get(url, url))
        last = end
    out.append(text[last:])
    return "".join(out)


def paragraph_html(paragraph: str, links: dict[str, str]) -> str:
    """One paragraph as HTML: the text escaped, each tracked link a link to its tracking address that shows the
    original address (so the reader sees where it leads)."""
    out, last = [], 0
    for start, end, url in find_urls(paragraph):
        target = links.get(url)
        if target is None:
            continue
        out.append(escape(paragraph[last:start]))
        out.append(f'<a href="{escape(target)}" style="color:#0176d3">{escape(url)}</a>')
        last = end
    out.append(escape(paragraph[last:]))
    return "".join(out).replace("\n", "<br>")


def pixel_html(token: str) -> str:
    return (f'<img src="{escape(open_url(token))}" width="1" height="1" alt="" '
            f'style="display:block;width:1px;height:1px;border:0;margin:0;padding:0">')


# ---------- the public requests: record, never act ----------

def automated_hint(user_agent: str | None, sent_at: datetime | None, at: datetime) -> str | None:
    """A cautious "possibly automated" reason, or None. None doesn't mean a person: most automated requests look
    like ordinary ones."""
    agent = (user_agent or "").lower()
    if not agent:
        return "no browser details"
    if any(word in agent for word in AUTOMATED_WORDS):
        return "looks like a scanner or a program"
    if sent_at is not None:
        sent = sent_at.astimezone(timezone.utc) if sent_at.tzinfo else sent_at.astimezone().astimezone(timezone.utc)
        if at - sent < SOON_AFTER_SENDING:
            return "seconds after sending"
    return None


def recipient_by_token(db: Session, token: str) -> CampaignRecipient | None:
    if not TOKEN_RE.match(token or ""):
        return None
    return db.scalar(select(CampaignRecipient).where(CampaignRecipient.tracking_token == token))


def link_by_key(db: Session, key: str) -> CampaignLink | None:
    if not KEY_RE.match(key or ""):
        return None
    return db.scalar(select(CampaignLink).where(CampaignLink.link_key == key))


def record(db: Session, row: CampaignRecipient, kind: str, user_agent: str | None, link: CampaignLink | None = None) -> None:
    """Saves one signal and this email's totals (one statement: two signals at once both count)."""
    at = utcnow()
    db.add(CampaignEvent(campaign_id=row.campaign_id, recipient_id=row.id, kind=kind, link_id=link.id if link else None,
                         occurred_at=at, automated_hint=automated_hint(user_agent, row.sent_at, at)))
    first, last, count = ((CampaignRecipient.first_open_at, CampaignRecipient.last_open_at, CampaignRecipient.open_events)
                          if kind == "open" else
                          (CampaignRecipient.first_click_at, CampaignRecipient.last_click_at, CampaignRecipient.click_events))
    db.execute(update(CampaignRecipient).where(CampaignRecipient.id == row.id).values(
        {first: func.coalesce(first, at), last: at, count: count + 1}))
    db.commit()


def record_open(db: Session, token: str, user_agent: str | None, method: str) -> bool:
    """An open signal for the email with this token, when everything allows it. Returns whether one was saved."""
    if method != "GET":  # a HEAD request only checks the image is there
        return False
    row = recipient_by_token(db, token)
    if row is None or not row.opens_tracked or row.status != "Sent" or not enabled(db):
        return False
    record(db, row, "open", user_agent)
    return True


def record_click(db: Session, token: str, link: CampaignLink, user_agent: str | None, method: str) -> bool:
    if method != "GET":
        return False
    row = recipient_by_token(db, token)
    if (row is None or row.campaign_id != link.campaign_id or not row.clicks_tracked or row.status != "Sent"
            or not enabled(db)):
        return False
    record(db, row, "click", user_agent, link)
    return True


# ---------- keeping signals for a limited time ----------

_last_purge: datetime | None = None


def purge(db: Session, *, force: bool = False) -> int:
    """Deletes signals older than the retention period (at most once an hour). Returns how many were deleted."""
    global _last_purge
    now = utcnow()
    if not force and _last_purge is not None and now - _last_purge < timedelta(hours=1):
        return 0
    _last_purge = now
    cutoff = now - timedelta(days=retention_days())
    result = db.execute(CampaignEvent.__table__.delete().where(CampaignEvent.occurred_at < cutoff))
    db.commit()
    if result.rowcount:
        log.info("Tracking: deleted %s signals older than %s days", result.rowcount, retention_days())
    return result.rowcount or 0


# ---------- the report ----------

def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


# The engagement cards' recipient groups (Campaigns > a campaign): sent emails only, each kind only where that email
# carried that tracking. They can overlap (a click doesn't imply an open: images may be blocked). Queued, failed,
# bounced, not sent and cancelled recipients, and emails sent without open tracking, are never "No Open Detected".
ENGAGEMENT_GROUPS = {
    "opened": lambda r: (r.status == "Sent", r.opens_tracked.is_(True), r.first_open_at.is_not(None)),
    "clicked": lambda r: (r.status == "Sent", r.clicks_tracked.is_(True), r.first_click_at.is_not(None)),
    "no_open": lambda r: (r.status == "Sent", r.opens_tracked.is_(True), r.first_open_at.is_(None)),
    "opens_not_tracked": lambda r: (r.status == "Sent", r.opens_tracked.is_(False)),
}


def engagement(db: Session, campaign) -> dict:
    """The campaign's engagement, kept apart from sending: recipients with signals (unique) and signals (repeated),
    with rates over the sent emails that carried that tracking."""
    rows = CampaignRecipient
    sent = (rows.campaign_id == campaign.id, rows.status == "Sent")
    q = lambda *where: db.scalar(select(func.count()).select_from(rows).where(*sent, *where)) or 0  # noqa: E731
    opens_sent, clicks_sent = q(rows.opens_tracked.is_(True)), q(rows.clicks_tracked.is_(True))
    opened, clicked = q(rows.first_open_at.is_not(None)), q(rows.first_click_at.is_not(None))
    open_events, click_events = db.execute(select(func.coalesce(func.sum(rows.open_events), 0),
                                                  func.coalesce(func.sum(rows.click_events), 0)).where(*sent)).one()
    flagged = dict(db.execute(select(CampaignEvent.kind, func.count()).where(
        CampaignEvent.campaign_id == campaign.id, CampaignEvent.automated_hint.is_not(None))
        .group_by(CampaignEvent.kind)).all())
    links = db.execute(select(CampaignLink.url, func.count(CampaignEvent.id),
                              func.count(func.distinct(CampaignEvent.recipient_id)))
                       .join(CampaignEvent, CampaignEvent.link_id == CampaignLink.id)
                       .where(CampaignLink.campaign_id == campaign.id, CampaignEvent.kind == "click")
                       .group_by(CampaignLink.url).order_by(func.count(CampaignEvent.id).desc())).all()
    return {
        "track_opens": campaign.track_opens, "track_clicks": campaign.track_clicks, "allowed_now": enabled(db),
        "sent": q(), "sent_with_open_tracking": opens_sent, "sent_with_click_tracking": clicks_sent,
        "recipients_with_open_signal": opened, "recipients_with_click_signal": clicked,
        "open_signal_rate_pct": _rate(opened, opens_sent), "click_signal_rate_pct": _rate(clicked, clicks_sent),
        "open_signals": int(open_events), "click_signals": int(click_events),
        "possibly_automated": {"open": flagged.get("open", 0), "click": flagged.get("click", 0)},
        "links": [{"url": url, "clicks": n, "recipients": people} for url, n, people in links],
        "retention_days": retention_days(),
        # recipients (not signals) in each engagement group: the cards and the recipient filter
        "groups": {key: db.scalar(select(func.count()).select_from(rows).where(
            rows.campaign_id == campaign.id, *where(rows))) or 0 for key, where in ENGAGEMENT_GROUPS.items()},
    }


def recipient_links(db: Session, recipient_ids: list[int]) -> dict[int, list[dict]]:
    """Each recipient's clicked links (this page's rows): the address, clicks, first and latest (UTC)."""
    if not recipient_ids:
        return {}
    out: dict[int, list[dict]] = {}
    for rid, url, n, first, last, flagged in db.execute(
            select(CampaignEvent.recipient_id, CampaignLink.url, func.count(), func.min(CampaignEvent.occurred_at),
                   func.max(CampaignEvent.occurred_at),
                   func.sum(case((CampaignEvent.automated_hint.is_not(None), 1), else_=0)))
            .join(CampaignLink, CampaignLink.id == CampaignEvent.link_id)
            .where(CampaignEvent.recipient_id.in_(recipient_ids), CampaignEvent.kind == "click")
            .group_by(CampaignEvent.recipient_id, CampaignLink.url)).all():
        out.setdefault(rid, []).append({"url": url, "clicks": n, "first_at": iso(first), "last_at": iso(last),
                                        "possibly_automated": int(flagged or 0)})
    return out


def recipient_out(r: CampaignRecipient, links: list[dict]) -> dict:
    return {"opens_tracked": r.opens_tracked, "clicks_tracked": r.clicks_tracked,
            "first_open_at": iso(r.first_open_at), "last_open_at": iso(r.last_open_at), "open_signals": r.open_events,
            "first_click_at": iso(r.first_click_at), "last_click_at": iso(r.last_click_at),
            "click_signals": r.click_events, "links": links}
