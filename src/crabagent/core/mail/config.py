from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import EmailConfig, async_session_factory
from crabagent.core.provider_store import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)


@dataclass
class MailConfig:
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    check_interval: int = 300
    enabled: bool = False


def _to_dict(cfg: MailConfig) -> dict:
    return {
        "imap_host": cfg.imap_host,
        "imap_port": cfg.imap_port,
        "imap_user": cfg.imap_user,
        "imap_pass": cfg.imap_pass,
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user,
        "smtp_pass": cfg.smtp_pass,
        "check_interval": cfg.check_interval,
        "enabled": cfg.enabled,
    }


async def get_config(user_id: int = 1) -> MailConfig | None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(EmailConfig).where(EmailConfig.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        cfg = MailConfig(
            imap_host=row.imap_host,
            imap_port=row.imap_port,
            imap_user=row.imap_user,
            imap_pass=decrypt_api_key(row.imap_pass) if row.imap_pass else "",
            smtp_host=row.smtp_host,
            smtp_port=row.smtp_port,
            smtp_user=row.smtp_user,
            smtp_pass=decrypt_api_key(row.smtp_pass) if row.smtp_pass else "",
            check_interval=row.check_interval,
            enabled=row.enabled,
        )
        return cfg


async def save_config(user_id: int, data: dict) -> MailConfig:
    async with async_session_factory() as db:
        result = await db.execute(
            select(EmailConfig).where(EmailConfig.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            row = EmailConfig(user_id=user_id)
            db.add(row)

        if "imap_host" in data:
            row.imap_host = data["imap_host"]
        if "imap_port" in data:
            row.imap_port = int(data["imap_port"])
        if "imap_user" in data:
            row.imap_user = data["imap_user"]
        if "imap_pass" in data and data["imap_pass"]:
            row.imap_pass = encrypt_api_key(data["imap_pass"])
        if "smtp_host" in data:
            row.smtp_host = data["smtp_host"]
        if "smtp_port" in data:
            row.smtp_port = int(data["smtp_port"])
        if "smtp_user" in data:
            row.smtp_user = data["smtp_user"]
        if "smtp_pass" in data and data["smtp_pass"]:
            row.smtp_pass = encrypt_api_key(data["smtp_pass"])
        if "check_interval" in data:
            row.check_interval = int(data["check_interval"])
        if "enabled" in data:
            row.enabled = bool(data["enabled"])

        await db.commit()
        await db.refresh(row)

    return await get_config(user_id) or MailConfig()


async def test_connection(user_id: int = 1) -> str:
    """Test IMAP and SMTP connection. Returns OK message or error."""
    cfg = await get_config(user_id)
    if not cfg:
        return "❌ No email configuration found."

    # Test IMAP
    try:
        import imaplib

        imap = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
        imap.login(cfg.imap_user, cfg.imap_pass)
        imap.select("INBOX")
        imap.logout()
        imap_ok = True
    except Exception as e:
        imap_ok = False
        imap_err = str(e)

    # Test SMTP
    try:
        import smtplib

        if cfg.smtp_port == 465:
            # Direct SSL connection (e.g. QQ Mail, 163)
            smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=10)
        else:
            # STARTTLS (e.g. Gmail, port 587)
            smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)
            smtp.starttls()
        smtp.login(cfg.smtp_user, cfg.smtp_pass)
        smtp.quit()
        smtp_ok = True
    except Exception as e:
        smtp_ok = False
        smtp_err = str(e)

    parts = []
    parts.append("✅ IMAP" if imap_ok else f"❌ IMAP: {imap_err}")
    parts.append("✅ SMTP" if smtp_ok else f"❌ SMTP: {smtp_err}")
    return " | ".join(parts)
