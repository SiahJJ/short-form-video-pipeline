"""Edge-triggered email alerts over SMTP. Configuration comes only from environment variables:

    NOTIFY_SMTP_HOST (default smtp.gmail.com)   NOTIFY_SMTP_PORT (default 587)
    NOTIFY_SMTP_USER   NOTIFY_SMTP_PASSWORD (an app password)   NOTIFY_TO (comma-separated)

`alert_once(key, active, ...)` sends one email when a condition becomes true and stays quiet until it has
cleared, so a stuck condition doesn't email you every five minutes.
"""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

STATE = Path(os.environ.get("NOTIFY_STATE", "notify_state.json"))


def send_email(subject: str, body: str) -> None:
    user, password = os.environ.get("NOTIFY_SMTP_USER"), os.environ.get("NOTIFY_SMTP_PASSWORD")
    to = [a.strip() for a in os.environ.get("NOTIFY_TO", user or "").split(",") if a.strip()]
    if not (user and password and to):
        raise RuntimeError("NOTIFY_SMTP_USER / NOTIFY_SMTP_PASSWORD / NOTIFY_TO are not configured")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.set_content(body)
    with smtplib.SMTP(os.environ.get("NOTIFY_SMTP_HOST", "smtp.gmail.com"),
                      int(os.environ.get("NOTIFY_SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)


def alert_once(key: str, active: bool, subject: str, body: str, send=send_email) -> bool:
    """Returns True if an email was sent this call."""
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    was = state.get(key, False)
    sent = False
    if active and not was:
        send(subject, body)
        sent = True
    if active != was:
        state[key] = active
        STATE.write_text(json.dumps(state), encoding="utf-8")
    return sent
