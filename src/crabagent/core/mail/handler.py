from __future__ import annotations

import logging

from crabagent.core.mail.config import MailConfig, get_config, save_config
from crabagent.core.mail.imap import ImapClient
from crabagent.core.mail.smtp import SmtpClient

logger = logging.getLogger(__name__)


async def get_imap_client(user_id: int = 1) -> ImapClient | None:
    """Get an authenticated IMAP client from config."""
    cfg = await get_config(user_id)
    if not cfg or not cfg.enabled or not cfg.imap_host:
        return None
    return ImapClient(cfg.imap_host, cfg.imap_port, cfg.imap_user, cfg.imap_pass)


async def get_smtp_client(user_id: int = 1) -> SmtpClient | None:
    """Get an authenticated SMTP client from config."""
    cfg = await get_config(user_id)
    if not cfg or not cfg.enabled or not cfg.smtp_host:
        return None
    return SmtpClient(cfg.smtp_host, cfg.smtp_port, cfg.smtp_user, cfg.smtp_pass)


async def check_new_emails(user_id: int = 1, limit: int = 5) -> list[dict]:
    """Check for new emails. Returns list of unseen email summaries."""
    client = await get_imap_client(user_id)
    if not client:
        return []
    try:
        emails = await client.fetch_unseen(limit)
        return emails
    except Exception as e:
        logger.error(f"Email check failed: {e}")
        return []
    finally:
        await client.close()


async def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    user_id: int = 1,
    attachments: list[str] | None = None,
    html: bool = False,
) -> dict:
    """Send an email via configured SMTP, optionally with file attachments."""
    client = await get_smtp_client(user_id)
    if not client:
        return {"status": "error", "message": "SMTP not configured"}
    try:
        result = await client.send(to, subject, body, reply_to, attachments, html)
        return result
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return {"status": "error", "message": str(e)}
