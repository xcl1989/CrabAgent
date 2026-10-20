"""Push notification channel API — status / config / test.

Mirrors ``serve/api/wechat.py`` style. Config is stored in the
``app_settings`` table (key=``push_config``); secrets are masked on read.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import get_db
from crabagent.core.push import PushNotification
from crabagent.core.push.config import PushConfig, load_config, save_config
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])


class PushConfigRequest(BaseModel):
    enabled: bool | None = None
    provider: str | None = None  # bark | ntfy
    bark_server: str | None = None
    bark_device_key: str | None = None
    ntfy_server: str | None = None
    ntfy_topic: str | None = None
    deep_link_base: str | None = None
    notify_task_done: bool | None = None
    notify_task_waiting: bool | None = None
    notify_schedule_result: bool | None = None
    notify_email_summary: bool | None = None
    sound: str | None = None
    time_sensitive: bool | None = None


class PushTestRequest(BaseModel):
    title: str = "🔔 CrabAgent 推送测试"
    body: str = "如果你看到这条通知，说明推送通道已打通。"


def _apply_updates(cfg: PushConfig, req: PushConfigRequest) -> None:
    """Copy provided fields onto cfg. Empty string for a secret means 'keep'."""
    data = req.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is None:
            continue
        # Masked echo-back guard: a masked value (starts with •••) means the
        # client round-tripped the masked config — keep the stored secret.
        if field in ("bark_device_key", "ntfy_topic") and isinstance(value, str) and value.startswith("•••"):
            continue
        setattr(cfg, field, value)


@router.get("/status")
async def get_status(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await load_config()
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "deep_link_base": cfg.deep_link_base,
        "notify_task_done": cfg.notify_task_done,
        "notify_task_waiting": cfg.notify_task_waiting,
        "notify_schedule_result": cfg.notify_schedule_result,
        "notify_email_summary": cfg.notify_email_summary,
        "sound": cfg.sound,
        "time_sensitive": cfg.time_sensitive,
        "configured": bool(cfg.bark_device_key or cfg.ntfy_topic),
        "config": cfg.masked(),
        "saved_at": cfg.saved_at,
    }


@router.put("/config")
async def update_config(
    req: PushConfigRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await load_config()
    _apply_updates(cfg, req)
    if req.provider and req.provider not in ("bark", "ntfy"):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="provider must be 'bark' or 'ntfy'")
    await save_config(cfg)
    return {"success": True, "config": (await load_config()).masked()}


@router.post("/test")
async def send_test(
    req: PushTestRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await PushNotification.send(req.title, req.body, category="")
    return {"success": ok}
