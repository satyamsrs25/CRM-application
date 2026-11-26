"""Sending email over SMTP.

Settings (environment variables):
  SMTP_HOST       mail server. In Docker this is the Mailpit test inbox (http://localhost:8026).
                  If empty, emails are not sent (used by the automatic tests).
  SMTP_PORT       default 1025 (Mailpit). Use 587 for most real mail servers.
  SMTP_USER / SMTP_PASSWORD / SMTP_TLS=true   for a real mail server: Outlook / Microsoft 365 is
                  smtp.office365.com, port 587, TLS, with the mailbox's own login
  MAIL_FROM       sender address, default crm@salestrack.local (Outlook SMTP: the SMTP_USER mailbox, or a mailbox
                  it has "Send As" rights for).
                  Every email goes out from this address, shown as "<user name> via SalesTrack";
                  replies go to the salesperson (Reply-To).
  MAIL_PROVIDER   smtp (default) or graph = Microsoft 365 / Outlook with OAuth (no SMTP password):
  MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET
                  an Azure app registration with the Mail.Send application permission (admin consent);
                  emails are sent from the MAIL_FROM mailbox through Microsoft Graph.
  MAIL_ASYNC      true (default) sends notification emails in the background after the save
  APP_URL         link used in notification emails, default http://localhost:5173

Emails queued during a request are sent only after the database commit succeeds,
so a failed save never sends an email.
"""
import base64
import html as html_text
import json
import re
import logging
import os
import smtplib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("crm.mail")


def settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "1025")),
        "user": os.getenv("SMTP_USER", ""),
        "password": password(),
        "tls": os.getenv("SMTP_TLS", "false").lower() == "true",
        "sender": os.getenv("MAIL_FROM", "crm@salestrack.local"),
        "app_url": os.getenv("APP_URL", "http://localhost:5173").rstrip("/"),
    }


def password() -> str:
    """The mailbox password. Outlook: used exactly as written. Gmail (testing): Google shows App Passwords in groups
    of four ("abcd efgh ijkl mnop"); the spaces aren't part of it, so they are removed."""
    value = os.getenv("SMTP_PASSWORD", "")
    if os.getenv("SMTP_HOST", "").strip().lower() == "smtp.gmail.com":
        value = value.replace(" ", "")
    return value


def provider() -> str:
    return os.getenv("MAIL_PROVIDER", "smtp").strip().lower()


def mode() -> dict:
    """Where emails go, without secrets. Used by GET /api/health/email."""
    cfg = settings()
    if provider() == "graph":
        ready = all(os.getenv(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"))
        return {"mode": "real email" if ready else "off", "provider": "Microsoft 365 (Graph, OAuth)",
                "sender": cfg["sender"],
                "detail": "Emails are sent from the Outlook mailbox" if ready
                else "MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET are needed"}
    if not cfg["host"]:
        return {"mode": "off", "detail": "SMTP_HOST is empty: emails are not sent"}
    test_inbox = cfg["host"] in ("mailpit", "localhost", "127.0.0.1") and cfg["port"] == 1025
    return {
        "mode": "test inbox" if test_inbox else "real email",
        "host": cfg["host"],
        "port": cfg["port"],
        "tls": cfg["tls"],
        "login": bool(cfg["user"]),
        "sender": cfg["sender"],
        "detail": "Emails land in Mailpit at http://localhost:8026" if test_inbox else "Emails are delivered to real inboxes",
    }


def app_link(path: str | None) -> str:
    return f"{settings()['app_url']}/#{path or '/'}"


# Name shown on system emails (notifications, reminders, welcome emails). Nobody reads replies to these.
SYSTEM_NAME = "SalesTrack (no-reply)"


def company_name() -> str:
    """The company name used in email wording (COMPANY_NAME in .env)."""
    return os.getenv("COMPANY_NAME", "").strip() or "SalesTrack"


def send(to: list[str], subject: str, body: str, *, cc: list[str] | None = None, sender_name: str = SYSTEM_NAME,
         reply_to: str | None = None, attachments: list[tuple[str, str, bytes]] = (), html: str | None = None) -> str | None:
    """Sends one email (html: a formatted version shown by mail apps; body stays the plain-text version).
    Returns None when sent, or the error text."""
    cfg = settings()
    if provider() == "graph":
        return send_graph(to, subject, body, cc=cc or [], sender_name=sender_name, reply_to=reply_to,
                          attachments=attachments, html=html)
    if not cfg["host"]:
        log.info("SMTP_HOST not set; email not sent: %s", subject)
        return None
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, cfg["sender"]))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for filename, content_type, data in attachments:
        main, _, sub = (content_type or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=filename)
    try:
        # port 465 uses SSL from the start; other ports (587) switch to TLS with STARTTLS
        connect = smtplib.SMTP_SSL if cfg["port"] == 465 else smtplib.SMTP
        with connect(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["tls"] and cfg["port"] != 465:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return None
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Email not sent (%s): %s", subject, exc)
        return str(exc) or exc.__class__.__name__


# ---------- Microsoft 365 / Outlook through Microsoft Graph (OAuth, client credentials) ----------

_graph_token: dict = {"value": "", "expires": 0.0}
GRAPH_MAX_ATTACHMENTS = 3 * 1024 * 1024  # sendMail accepts up to about 3 MB of attachments in one request


def _post_json(url: str, data: bytes, headers: dict) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode() or "{}"
        return json.loads(text)


def graph_token() -> str:
    if _graph_token["value"] and _graph_token["expires"] > time.time() + 60:
        return _graph_token["value"]
    tenant = os.getenv("MS_TENANT_ID", "")
    form = urllib.parse.urlencode({
        "client_id": os.getenv("MS_CLIENT_ID", ""),
        "client_secret": os.getenv("MS_CLIENT_SECRET", ""),
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    result = _post_json(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", form,
                        {"Content-Type": "application/x-www-form-urlencoded"})
    _graph_token.update(value=result["access_token"], expires=time.time() + int(result.get("expires_in", 3600)))
    return _graph_token["value"]


def send_graph(to: list[str], subject: str, body: str, *, cc: list[str], sender_name: str,
               reply_to: str | None, attachments, html: str | None = None) -> str | None:
    sender = settings()["sender"]
    if not all(os.getenv(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET")):
        return "Outlook (Graph) is not set up: MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET are needed"
    if sum(len(d) for _, _, d in attachments) > GRAPH_MAX_ATTACHMENTS:
        return "Attachments over 3 MB in total can't be sent through Outlook yet"
    people = lambda addresses: [{"emailAddress": {"address": a}} for a in addresses]  # noqa: E731
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html} if html else {"contentType": "Text", "content": body},
        "from": {"emailAddress": {"address": sender, "name": sender_name}},
        "toRecipients": people(to),
        "ccRecipients": people(cc),
        "replyTo": people([reply_to] if reply_to else []),
        "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": n, "contentType": t,
                         "contentBytes": base64.b64encode(d).decode()} for n, t, d in attachments],
    }
    try:
        _post_json(f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
                   json.dumps({"message": message, "saveToSentItems": True}).encode(),
                   {"Authorization": f"Bearer {graph_token()}", "Content-Type": "application/json"})
        return None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        log.warning("Email not sent through Graph (%s): %s %s", subject, exc.code, detail)
        return f"Outlook refused the email ({exc.code}): {detail}"
    except (OSError, KeyError, ValueError) as exc:
        log.warning("Email not sent through Graph (%s): %s", subject, exc)
        return str(exc) or exc.__class__.__name__


# ---------- outbox: send after commit ----------

def queue(db: Session, to: str, subject: str, body: str, *, sender_name: str = SYSTEM_NAME,
          html: str | None = None) -> None:
    db.info.setdefault("outbox", []).append((to, subject, body, sender_name, html))


def _deliver(messages: list[tuple[str, str, str, str, str | None]]) -> None:
    for to, subject, body, sender_name, html in messages:
        send([to], subject, body, sender_name=sender_name, html=html)


# ---------- standard capital letters in automatic emails ----------
# Subjects in title case ("[SalesTrack] Lead Assigned to You"), people's names with capitals ("vikram sake" ->
# "Vikram Sake") and every line starting with a capital. Words that already have a capital (IBM, iPhone, McKay) and
# anything that isn't a word (emails, links, numbers) are left as they are. Campaign emails are the sender's own words
# and are not changed.
BUTTON_LABEL = "View URL"  # the link button in automatic emails
SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "off", "on", "or", "per", "so",
               "the", "to", "up", "via", "vs", "yet"}
PERSON_LABELS = {"Lead", "Contact", "Owner", "Name", "Salesperson", "Manager", "Assigned by", "Assigned to",
                 "Requested by", "Approved by", "Rejected by", "Deleted by", "Restored by", "Created by", "Changed by",
                 "Transferred by", "Transferred to", "Previous owner", "New owner", "Username"}
_WORD = re.compile(r"^[a-z][a-z']*$")


def title_case(text: str) -> str:
    """An email subject in title case: "Lead assigned to you" -> "Lead Assigned to You"."""
    words = text.split(" ")
    real = [i for i, w in enumerate(words) if w[:1].isalpha()]
    out = []
    for i, word in enumerate(words):
        if not _WORD.match(word) or (word in SMALL_WORDS and real and i not in (real[0], real[-1])):
            out.append(word)
        else:
            out.append(word[0].upper() + word[1:])
    return " ".join(out)


def person_name(name: str | None) -> str:
    """A person's name with standard capitals: "vikram sake" / "VIKRAM SAKE" -> "Vikram Sake", "o'brien" ->
    "O'Brien". Mixed-case names (McKay, DeSouza) and short all-caps parts (initials such as "RK") stay as typed."""
    if not name:
        return name or ""

    def fix(part: str) -> str:
        if part.islower() or (part.isupper() and len(part) > 2):
            return re.sub(r"(^|[-'])([a-z])", lambda m: m.group(1) + m.group(2).upper(), part.lower())
        return part
    return " ".join(fix(word) for word in name.split(" "))


def tidy_line(line: str) -> str:
    """One line of an automatic email: a person's name after "Lead:", "Owner:"... gets capitals, and a line that
    starts with a lowercase word starts with a capital (not when it starts with an email address or a link)."""
    first = line.split(" ", 1)[0]
    if _WORD.match(first.rstrip(":")) and "@" not in first and "://" not in first:
        line = line[0].upper() + line[1:]
    detail = re.match(r"^([A-Z][A-Za-z ]{0,28}): (.+)$", line)
    if detail and detail.group(1) in PERSON_LABELS and "@" not in detail.group(2):
        return f"{detail.group(1)}: {person_name(detail.group(2))}"
    return line


def tidy_text(text: str) -> str:
    return "\n".join(tidy_line(line) for line in text.split("\n"))


# ---------- notification emails: the same text, laid out (Outlook joins the lines of plain-text emails) ----------

_DETAIL = re.compile(r"^([A-Z][A-Za-z /]{0,28}): (.+)$")  # "Company: Acme" -> a row of the details table


def notification_html(first_name: str, message: str, link_url: str | None, why: str) -> str:
    """The HTML version of a notification email: each line of the message on its own line, "Label: value" lines as a
    details table, "- " lines as a list, and a View URL button (BUTTON_LABEL)."""
    esc = html_text.escape
    parts, rows, items = [], [], []

    def flush():
        if rows:
            parts.append('<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:8px 0 14px">'
                         + "".join(f'<tr><td style="padding:4px 16px 4px 0;color:#5c5c5c;vertical-align:top;'
                                   f'white-space:nowrap">{esc(k)}</td><td style="padding:4px 0;color:#181818;'
                                   f'font-weight:600">{esc(v)}</td></tr>' for k, v in rows) + "</table>")
            rows.clear()
        if items:
            parts.append('<ul style="margin:4px 0 14px;padding-left:20px">'
                         + "".join(f'<li style="margin:2px 0">{esc(i)}</li>' for i in items) + "</ul>")
            items.clear()

    for line in message.splitlines():
        line = line.strip()
        detail = _DETAIL.match(line)
        if detail and detail.group(2)[:1].islower() and line.endswith("."):
            detail = None  # a sentence ("No open tasks: add the next follow-up."), not a detail
        if not line:
            flush()
        elif line.startswith("- "):
            if rows:
                flush()
            items.append(line[2:])
        elif detail:
            if items:
                flush()
            rows.append(detail.groups())
        else:
            flush()
            parts.append(f'<p style="margin:0 0 10px">{esc(line)}</p>')
    flush()
    button = (f'<p style="margin:18px 0"><a href="{esc(link_url)}" style="background:#0176d3;color:#ffffff;'
              f'padding:9px 18px;border-radius:6px;text-decoration:none;font-weight:600">{BUTTON_LABEL}</a></p>'
              if link_url else "")
    return ('<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#181818">'
            f'<p style="margin:0 0 12px">Hi {esc(first_name)},</p>{"".join(parts)}{button}'
            f'<p style="margin:18px 0 0;color:#747474;font-size:12px">{esc(why)}</p></div>')


@event.listens_for(Session, "after_commit")
def _send_outbox(session: Session) -> None:
    messages = session.info.pop("outbox", [])
    if not messages:
        return
    # Real mail servers can take a few seconds per email; send in the background so a click
    # (e.g. Mark Stage as Complete) returns at once. MAIL_ASYNC=false sends before returning (tests).
    if os.getenv("MAIL_ASYNC", "true").lower() == "true":
        threading.Thread(target=_deliver, args=(messages,), daemon=True, name="crm-mail").start()
    else:
        _deliver(messages)


@event.listens_for(Session, "after_rollback")
def _clear_outbox(session: Session) -> None:
    session.info.pop("outbox", None)
