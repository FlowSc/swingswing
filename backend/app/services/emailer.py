from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


logger = logging.getLogger(__name__)


async def send_admin_email(subject: str, body: str) -> bool:
    settings = get_settings()
    if not settings.admin_report_email:
        logger.info("Admin email skipped: ADMIN_REPORT_EMAIL is not configured")
        return False
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        logger.info("Admin email skipped: SMTP settings are not configured")
        return False

    from_email = settings.smtp_from_email or settings.smtp_username
    return await asyncio.to_thread(
        _send_email_sync,
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
        return True
    except Exception:
        logger.exception("Admin email failed")
        return False
