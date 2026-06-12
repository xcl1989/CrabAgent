"""WeChat iLink Bot API routes.

Endpoints:
- ``GET  /api/wechat/status``   — login status + config
- ``POST /api/wechat/qrcode``   — start QR login (returns QR image)
- ``GET  /api/wechat/qrcode/status`` — poll QR scan status
- ``POST /api/wechat/logout``   — clear credentials
- ``PUT  /api/wechat/config``   — update settings (enabled, allowed_users, etc.)
- ``POST /api/wechat/test``     — send a test message
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat", tags=["wechat"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class WeChatStatus(BaseModel):
    logged_in: bool = False
    enabled: bool = False
    account_id: str = ""
    auto_reply: bool = True
    workspace: str = ""
    allowed_users: list[str] = []
    notify_task_overdue: bool = True
    notify_schedule_result: bool = True
    notify_email_summary: bool = False
    notify_target_user: str = ""


class QRCodeResponse(BaseModel):
    qrcode: str = ""
    qrcode_img_base64: str = ""  # base64 image data (if available)
    qrcode_url: str = ""          # QR URL link (if image not available)


class QRCodeStatusResponse(BaseModel):
    status: str = "wait"  # wait | scanned | confirmed | expired
    logged_in: bool = False


class UpdateConfigRequest(BaseModel):
    enabled: bool | None = None
    auto_reply: bool | None = None
    workspace: str | None = None
    allowed_users: list[str] | None = None
    notify_task_overdue: bool | None = None
    notify_schedule_result: bool | None = None
    notify_email_summary: bool | None = None
    notify_target_user: str | None = None


class TestMessageRequest(BaseModel):
    text: str = "Hello from CrabAgent!"


# ---------------------------------------------------------------------------
# Module-level state for QR login flow
# ---------------------------------------------------------------------------

_qr_state: dict[str, str] = {}  # session_key → qrcode string
_qr_client: dict[str, object] = {}  # session_key → WeChatClient


def _extract_base64_image(content: str) -> str:
    """Extract base64 image data from qrcode_img_content.

    The content can be:
    - data:image/png;base64,xxx  → extract base64 part
    - raw base64                 → return as-is
    - URL / SVG / other          → return empty (use qrcode_url instead)
    """
    if not content:
        return ""
    if content.startswith("data:image/"):
        # data:image/png;base64,xxxx
        parts = content.split(",", 1)
        if len(parts) == 2:
            return parts[1]
        return ""
    # Check if it's pure base64 (starts with / or i and reasonable length)
    import re

    stripped = content.strip()
    if re.match(r'^[A-Za-z0-9+/=]{50,}$', stripped) and not stripped.startswith("http"):
        return stripped
    return ""


def _extract_qr_url(content: str, qrcode: str) -> str:
    """Extract QR URL for display.

    If content is a URL, return it. Otherwise return the qrcode string itself
    (which may be a URL or a code that the frontend can render as QR).
    """
    if content and content.startswith("http"):
        return content
    if qrcode and qrcode.startswith("http"):
        return qrcode
    return qrcode  # May be a code string; frontend can generate QR from it


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(
    user: User = Depends(get_current_user),
):
    """Get current WeChat login status and configuration."""
    from crabagent.core.wechat import load_config

    cfg = await load_config()
    return WeChatStatus(
        logged_in=bool(cfg.bot_token),
        enabled=cfg.enabled,
        account_id=cfg.account_id,
        auto_reply=cfg.auto_reply,
        workspace=cfg.workspace,
        allowed_users=cfg.allowed_users,
        notify_task_overdue=cfg.notify_task_overdue,
        notify_schedule_result=cfg.notify_schedule_result,
        notify_email_summary=cfg.notify_email_summary,
        notify_target_user=cfg.notify_target_user,
    )


@router.post("/qrcode")
async def start_qr_login(
    user: User = Depends(get_current_user),
):
    """Start QR code login flow. Returns base64-encoded QR image."""
    from crabagent.core.wechat import WeChatClient

    client = WeChatClient()
    try:
        result = await client.get_qrcode()
    except Exception as e:
        logger.error("[WeChat API] Failed to get QR code: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to get QR code: {e}")

    # Store for polling
    session_key = f"user_{user.id}"
    _qr_state[session_key] = result.qrcode
    _qr_client[session_key] = client

    return QRCodeResponse(
        qrcode=result.qrcode,
        qrcode_img_base64=_extract_base64_image(result.qrcode_img_content),
        qrcode_url=_extract_qr_url(result.qrcode_img_content, result.qrcode),
    )


@router.get("/qrcode/status")
async def check_qr_status(
    user: User = Depends(get_current_user),
):
    """Poll QR code scan status."""
    from crabagent.core.wechat.client import WeChatClient

    session_key = f"user_{user.id}"
    qrcode = _qr_state.get(session_key)
    client = _qr_client.get(session_key)

    if not qrcode or not client:
        raise HTTPException(status_code=400, detail="No active QR login session")

    try:
        result = await client.poll_qrcode(qrcode)  # type: ignore[attr-defined]
    except Exception as e:
        logger.error("[WeChat API] QR poll failed: %s", e)
        return QRCodeStatusResponse(status="error", logged_in=False)

    status = result.get("status", "wait")
    logged_in = False

    if status == "confirmed":
        creds = result.get("credentials")
        if creds:
            # Cleanup QR state FIRST so subsequent polls don't repeat
            _qr_state.pop(session_key, None)
            _qr_client.pop(session_key, None)
            logged_in = True

            # Persist credentials
            try:
                client.apply_credentials(creds)  # type: ignore[attr-defined]
                from crabagent.core.wechat.config import load_config, save_config

                cfg = await load_config()
                cfg.bot_token = creds.bot_token
                cfg.base_url = creds.base_url
                cfg.account_id = creds.ilink_bot_id
                cfg.enabled = True
                await save_config(cfg)
                logger.info("[WeChat API] Credentials persisted, starting message loop")
            except Exception as e:
                logger.error("[WeChat API] Failed to persist credentials: %s", e)

            # Start the message loop (non-blocking — don't fail login if this errors)
            try:
                await _ensure_message_loop_running()
            except Exception as e:
                logger.error("[WeChat API] Failed to start message loop: %s", e)

    return QRCodeStatusResponse(status=status, logged_in=logged_in)


@router.post("/logout")
async def wechat_logout(
    user: User = Depends(get_current_user),
):
    """Logout and clear WeChat credentials."""
    from crabagent.core.wechat import logout as do_logout

    # Stop the message loop
    await _stop_message_loop()

    await do_logout()
    return {"success": True}


@router.put("/config")
async def update_config(
    req: UpdateConfigRequest,
    user: User = Depends(get_current_user),
):
    """Update WeChat configuration settings."""
    from crabagent.core.wechat.config import load_config, save_config

    cfg = await load_config()
    updates = req.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(cfg, key, value)
    await save_config(cfg)

    # Start/stop message loop based on enabled flag
    if cfg.enabled and cfg.bot_token:
        await _ensure_message_loop_running()
    else:
        await _stop_message_loop()

    return {"success": True, "config": cfg.to_dict()}


@router.post("/test")
async def send_test_message(
    req: TestMessageRequest,
    user: User = Depends(get_current_user),
):
    """Send a test message to verify the channel works.

    Uses the running message loop's client (which has cached context_tokens
    from received messages). Falls back to creating a new client if needed.
    """
    from crabagent.serve.scheduler import get_scheduler

    sched = get_scheduler()
    loop = getattr(sched, "_wechat_loop", None)
    client = loop.client if (loop and loop._running) else None

    if client and client._context_store:
        # Use the running loop's client with cached context_token
        user_id = next(iter(client._context_store))
        context_token = client._context_store[user_id]
        success = await client.send_message(user_id, req.text, context_token)
    else:
        from crabagent.core.wechat import WeChatNotification

        success = await WeChatNotification.send(req.text)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="发送失败 — 需要先从微信给 Bot 发一条消息建立会话",
        )
    return {"success": True}


# ---------------------------------------------------------------------------
# WeChat conversation history
# ---------------------------------------------------------------------------

class WeChatConversationItem(BaseModel):
    session_id: str
    title: str
    workspace: str = ""
    model: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0
    last_message: str = ""


@router.get("/conversations", response_model=list[WeChatConversationItem])
async def list_wechat_conversations(
    user: User = Depends(get_current_user),
):
    """List all WeChat conversations with last message preview."""
    from sqlalchemy import func, select

    from crabagent.core.database import Conversation, Message as DBMessage, async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.source == "wechat")
            .order_by(Conversation.updated_at.desc())
        )
        convs = result.scalars().all()

        items: list[WeChatConversationItem] = []
        for conv in convs:
            # Get message count and last message
            count_result = await db.execute(
                select(func.count(DBMessage.id)).where(DBMessage.conversation_id == conv.id)
            )
            msg_count = count_result.scalar() or 0

            last_result = await db.execute(
                select(DBMessage)
                .where(
                    DBMessage.conversation_id == conv.id,
                    DBMessage.content != "",
                )
                .order_by(DBMessage.id.desc())
                .limit(1)
            )
            last_msg = last_result.scalar_one_or_none()
            last_text = ""
            if last_msg and last_msg.content:
                last_text = last_msg.content[:80]

            items.append(WeChatConversationItem(
                session_id=conv.session_id,
                title=conv.title,
                workspace=conv.workspace,
                model=conv.model,
                created_at=conv.created_at.isoformat() if conv.created_at else None,
                updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
                message_count=msg_count,
                last_message=last_text,
            ))
        return items
# ---------------------------------------------------------------------------

async def _ensure_message_loop_running():
    """Start the WeChat message loop if not already running."""
    from crabagent.core.wechat import WeChatMessageLoop, get_authenticated_client

    from crabagent.serve.scheduler import get_scheduler

    sched = get_scheduler()
    if hasattr(sched, "_wechat_loop") and sched._wechat_loop and sched._wechat_loop._running:
        return  # Already running

    client = await get_authenticated_client()
    if not client:
        return

    loop = WeChatMessageLoop(client)
    sched._wechat_loop = loop
    await loop.start()
    logger.info("[WeChat API] Message loop started")


async def _stop_message_loop():
    """Stop the WeChat message loop."""
    from crabagent.serve.scheduler import get_scheduler

    sched = get_scheduler()
    loop = getattr(sched, "_wechat_loop", None)
    if loop and loop._running:
        await loop.stop()
    sched._wechat_loop = None
    logger.info("[WeChat API] Message loop stopped")
