from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


logger = logging.getLogger(__name__)


async def send_admin_email(subject: str, body: str) -> bool:
    return (await send_admin_email_result(subject, body))["sent"]


async def send_admin_email_result(subject: str, body: str) -> dict:
    settings = get_settings()
    if not settings.admin_report_email:
        message = "ADMIN_REPORT_EMAIL is not configured"
        logger.info("Admin email skipped: %s", message)
        return {"sent": False, "stage": "email_config", "error": message}
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        message = "SMTP settings are not configured"
        logger.info("Admin email skipped: %s", message)
        return {"sent": False, "stage": "email_config", "error": message}

    from_email = settings.smtp_from_email or settings.smtp_username
    return await asyncio.to_thread(
        _send_email_result_sync,
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_username,
        settings.smtp_password,
        from_email,
        settings.admin_report_email,
        subject,
        body,
    )


def _send_email_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> bool:
    return _send_email_result_sync(host, port, username, password, from_email, to_email, subject, body)["sent"]


def _send_email_result_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> dict:
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
        return {"sent": True, "stage": "sent", "error": None}
    except Exception as exc:
        logger.exception("Admin email failed")
        return {"sent": False, "stage": "smtp", "error": str(exc)}
