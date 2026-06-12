"""iLink Bot authentication flow.

Manages QR code login and credential persistence.
Credentials (bot_token) are encrypted at rest using Fernet.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from crabagent.core.wechat.client import LoginCredentials, QRCodeResult, WeChatClient
from crabagent.core.wechat.config import WeChatConfig, load_config, save_config

logger = logging.getLogger(__name__)

# QR poll interval (seconds)
_QR_POLL_INTERVAL = 2.0
# QR expiry (seconds)
_QR_MAX_WAIT = 120.0


async def start_login(client: WeChatClient) -> QRCodeResult:
    """Initiate QR code login.

    Returns a :class:`QRCodeResult` containing the QR code and image.
    """
    return await client.get_qrcode()


async def wait_for_login(
    client: WeChatClient,
    qrcode: str,
    *,
    timeout: float = _QR_MAX_WAIT,
    on_status: Any = None,
) -> LoginCredentials | None:
    """Poll QR code status until confirmed or expired.

    Args:
        client: The WeChatClient instance.
        qrcode: The QR code string from :func:`start_login`.
        timeout: Maximum wait time in seconds.
        on_status: Optional callback ``async (status: str, data: dict) -> None``.

    Returns:
        :class:`LoginCredentials` on success, ``None`` on timeout/expiry.
    """
    elapsed = 0.0
    while elapsed < timeout:
        try:
            result = await client.poll_qrcode(qrcode)
        except Exception as e:
            logger.error("[iLink] QR poll error: %s", e)
            await asyncio.sleep(3.0)
            elapsed += 3.0
            continue

        status = result.get("status", "wait")
        if on_status:
            await on_status(status, result)

        if status == "confirmed":
            creds = result.get("credentials")
            if creds:
                client.apply_credentials(creds)
                await _persist_credentials(creds)
                return creds
            logger.error("[iLink] Confirmed but no credentials in response")
            return None

        if status == "expired":
            logger.info("[iLink] QR code expired")
            return None

        await asyncio.sleep(_QR_POLL_INTERVAL)
        elapsed += _QR_POLL_INTERVAL

    logger.info("[iLink] QR login timed out after %.0fs", timeout)
    return None


async def _persist_credentials(creds: LoginCredentials) -> None:
    """Save login credentials to the config (token encrypted)."""
    cfg = await load_config()
    cfg.bot_token = creds.bot_token
    cfg.base_url = creds.base_url
    cfg.account_id = creds.ilink_bot_id  # store ilink_bot_id as account_id
    cfg.enabled = True
    await save_config(cfg)
    logger.info("[iLink] Credentials persisted (bot_id=%s)", creds.ilink_bot_id)


async def get_authenticated_client() -> WeChatClient | None:
    """Build a WeChatClient from saved config if credentials exist.

    Returns ``None`` if not logged in.
    """
    cfg = await load_config()
    if not cfg.bot_token:
        return None

    client = WeChatClient(
        base_url=cfg.base_url,
        bot_token=cfg.bot_token,
    )
    client.account_id = cfg.account_id
    return client


async def logout() -> None:
    """Clear saved credentials and disable the channel."""
    cfg = await load_config()
    cfg.bot_token = ""
    cfg.account_id = ""
    cfg.enabled = False
    await save_config(cfg)
    logger.info("[iLink] Logged out — credentials cleared")


async def is_logged_in() -> bool:
    """Check if valid credentials are stored."""
    cfg = await load_config()
    return bool(cfg.bot_token and cfg.enabled)
