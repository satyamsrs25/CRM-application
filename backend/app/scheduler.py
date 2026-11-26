"""Background checks for task reminders and overdue tasks (runs every minute while the API is up).

- Reminder: when a task's reminder time is reached, the owner gets a bell reminder and an email (once).
            This covers follow-ups, demo reminders ("Conduct demo", "Prepare for demo") and close-date reminders.
- Overdue:  once a day, the owner of each open task that is past its due date gets an email and a bell reminder.
- Demos:    "Conduct demo" and "Prepare for demo" are reminded before the demo only. Once the demo time has passed the
            task shows as overdue in Tasks, but no more bell reminders or emails are sent (DEMO_TASKS).
- No activity: once a day, a summary of open leads and opportunities untouched for 3+ days (app/idle_reminders.py)
            to their owners, the owners' Managers and the Admin.
- Deleted Leads: a deleted lead's copy is deleted for good after 90 days (app/routers/deleted_leads.py).
Reminders stay on the bell until the task is done (see GET /api/notifications).
"""
import asyncio
import logging
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import AUTO_TASKS, DEMO_PREP_TASK
from app.idle_reminders import send_idle_reminders
from app.models import Notification, Task
from app.routers.deleted_leads import purge_expired
from app.services import notify, now, record_link, start_of_today

log = logging.getLogger("crm.scheduler")
DEMO_TASKS = (AUTO_TASKS["Demo"][0], DEMO_PREP_TASK)  # reminded before the demo, silent once it has passed


def run_checks(db: Session) -> dict:
    current = now()
    reminders = db.scalars(
        select(Task).where(Task.status == "Open", Task.reminder_at.is_not(None),
                           Task.reminder_at <= current, Task.reminder_sent.is_(False))
    ).all()
    for task in reminders:
        if task.title in DEMO_TASKS and task.due_date < current:
            task.reminder_sent = True  # the demo is past (e.g. the server was off at reminder time): no reminder now
            continue
        message = f"{task.title} is due {task.due_date:%d %b %Y %I:%M %p}."
        if task.description:
            message += f"\n{task.description}"
        notify(db, task.owner_id, "Task reminder", message, kind="reminder",
               task_id=task.id, link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id))
        task.reminder_sent = True

    today = start_of_today()
    overdue = db.scalars(select(Task).where(Task.status == "Open", Task.due_date < today,
                                            Task.title.not_in(DEMO_TASKS))).all()  # a past demo: overdue, no emails
    sent_today = set(db.scalars(
        select(Notification.task_id).where(Notification.title == "Task overdue", Notification.created_at >= today)
    ).all())
    count = 0
    for task in overdue:
        if task.id in sent_today:
            continue
        days = (today.date() - task.due_date.date()).days
        notify(db, task.owner_id, "Task overdue",
               f"{task.title} was due {task.due_date:%d %b %Y} ({days} day{'s' if days != 1 else ''} ago).",
               task_id=task.id, link=record_link(lead_id=task.lead_id, opportunity_id=task.opportunity_id), kind="reminder")
        count += 1
    idle = send_idle_reminders(db)
    expired = purge_expired(db)
    db.commit()
    if expired:
        log.info("Deleted Leads older than 90 days removed for good: %s", expired)
    return {"reminders": len(reminders), "overdue": count, "no_activity": idle}


async def loop(session_factory) -> None:
    interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    while True:
        try:
            def work():
                with session_factory() as db:
                    return run_checks(db)
            result = await asyncio.to_thread(work)
            if any(result.values()):
                log.info("Notifications sent at %s: %s", datetime.now(), result)
        except Exception:  # keep the loop alive; the next run tries again
            log.exception("Reminder check failed")
        await asyncio.sleep(interval)
