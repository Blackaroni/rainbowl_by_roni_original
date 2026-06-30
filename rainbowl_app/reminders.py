from __future__ import annotations

import smtplib
import threading
import time
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from typing import Any

from .config import ReminderEmailConfig
from .db import Repository


@dataclass(frozen=True)
class ReminderDispatchResult:
    reminder_date: str
    reminders_found: int
    emails_sent: int
    notifications_logged: int
    dry_run: bool
    skipped: bool = False


def dispatch_pending_order_reminders(
    repository: Repository,
    email_config: ReminderEmailConfig,
    *,
    reminder_date: date | None = None,
    dry_run: bool = False,
) -> ReminderDispatchResult:
    reminder_date = reminder_date or date.today()
    reminders = repository.list_due_order_reminders(reminder_date)
    if not reminders:
        return ReminderDispatchResult(
            reminder_date=reminder_date.isoformat(),
            reminders_found=0,
            emails_sent=0,
            notifications_logged=0,
            dry_run=dry_run,
        )

    if not dry_run and not email_config.can_send_email():
        raise ValueError(
            "Reminder email settings are incomplete. Configure RAINBOWL_SMTP_USER, "
            "RAINBOWL_SMTP_PASSWORD, and RAINBOWL_SMTP_SENDER."
        )

    subject, body = build_pending_order_reminder_email(reminders, reminder_date)
    if dry_run:
        print(subject)
        print()
        print(body)
        return ReminderDispatchResult(
            reminder_date=reminder_date.isoformat(),
            reminders_found=len(reminders),
            emails_sent=0,
            notifications_logged=0,
            dry_run=True,
        )

    send_email(email_config, subject, body)
    logged = repository.record_order_reminder_notifications(
        reminders,
        recipient_email=email_config.recipient_email,
        reminder_date=reminder_date,
        email_subject=subject,
    )
    return ReminderDispatchResult(
        reminder_date=reminder_date.isoformat(),
        reminders_found=len(reminders),
        emails_sent=1,
        notifications_logged=logged,
        dry_run=False,
    )


def build_pending_order_reminder_email(
    reminders: list[dict[str, Any]],
    reminder_date: date,
) -> tuple[str, str]:
    subject = f"Rainbowl pending order reminders for {reminder_date.isoformat()}"
    lines = [
        f"Pending order reminders for {reminder_date.isoformat()}",
        "",
        "This alert includes pending, processing, and ready orders due in 1 or 2 days.",
        "",
    ]

    for days_before in (1, 2):
        matching = [reminder for reminder in reminders if int(reminder["days_before"]) == days_before]
        if not matching:
            continue
        lines.append(f"Due in {days_before} day{'s' if days_before != 1 else ''}:")
        for reminder in matching:
            lines.append(
                " - "
                f"{reminder['order_number']} | {reminder['customer_name']} | collect {reminder['requested_collection_date']} | "
                f"status {reminder['fulfillment_status']} | payment {reminder['payment_status']} | "
                f"total {reminder['order_total']:.2f} | balance {reminder['balance_due']:.2f}"
            )
            if reminder.get("customer_phone_number"):
                lines.append(f"   phone: {reminder['customer_phone_number']}")
            if reminder.get("customer_location"):
                lines.append(f"   location: {reminder['customer_location']}")
        lines.append("")

    return subject, "\n".join(lines).strip()


def send_email(email_config: ReminderEmailConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_config.sender_email
    message["To"] = email_config.recipient_email
    message.set_content(body)

    with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port, timeout=30) as smtp:
        if email_config.use_starttls:
            smtp.starttls()
        smtp.login(email_config.smtp_user, email_config.smtp_password)
        smtp.send_message(message)


def start_reminder_loop(repository: Repository, email_config: ReminderEmailConfig) -> threading.Thread | None:
    if not email_config.is_ready():
        return None

    def worker() -> None:
        while True:
            try:
                dispatch_pending_order_reminders(repository, email_config)
            except Exception as exc:  # pragma: no cover
                print(f"Reminder loop error: {exc}")
            time.sleep(email_config.interval_minutes * 60)

    thread = threading.Thread(target=worker, name="rainbowl-reminder-loop", daemon=True)
    thread.start()
    return thread
