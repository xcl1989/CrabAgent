"""WeChat (iLink Bot) configuration management.

Stores credentials and settings in the ``app_settings`` table using
a JSON blob under key ``wechat_config``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_SETTING_KEY = "wechat_config"


@dataclass
class WeChatConfig:
    """Runtime configuration for a single WeChat iLink Bot binding."""

    enabled: bool = False
    bot_token: str = ""          # Bearer token — Fernet-encrypted at rest
    account_id: str = ""         # iLink account ID
    base_url: str = "https://ilinkai.weixin.qq.com"
    auto_reply: bool = True      # Auto-reply to incoming messages via Agent
    workspace: str = ""           # Working directory for WeChat Agent (empty = cwd)
    allowed_users: list[str] = field(default_factory=list)  # Empty = everyone
    # Notification toggles
    notify_task_overdue: bool = True
    notify_schedule_result: bool = True
    notify_email_summary: bool = False
    # Notification target — auto-populated from first incoming message
    notify_target_user: str = ""          # WeChat user ID to push notifications to
    cached_context_token: str = ""        # Persisted context_token for push
    # Internal metadata
    saved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WeChatConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Persistence helpers (async, via AppSetting table)
# ---------------------------------------------------------------------------

async def load_config() -> WeChatConfig:
    """Load WeChat config from the ``app_settings`` table."""
    from sqlalchemy import select

    from crabagent.core.database import AppSetting, async_session_factory

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(AppSetting).where(AppSetting.key == _SETTING_KEY)
            )
            row = result.scalar_one_or_none()
            if row and row.value:
                return WeChatConfig.from_dict(json.loads(row.value))
    except Exception as e:
        logger.warning("Failed to load wechat config: %s", e)
    return WeChatConfig()


async def save_config(cfg: WeChatConfig) -> None:
    """Persist WeChat config to the ``app_settings`` table."""
    import json as _json

    from sqlalchemy import select

    from crabagent.core.database import AppSetting, async_session_factory

    cfg.saved_at = datetime.now().isoformat()
    blob = _json.dumps(cfg.to_dict(), ensure_ascii=False)

    async with async_session_factory() as db:
        result = await db.execute(
            select(AppSetting).where(AppSetting.key == _SETTING_KEY)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = blob
        else:
            db.add(AppSetting(key=_SETTING_KEY, value=blob))
        await db.commit()
    logger.info("WeChat config saved (enabled=%s)", cfg.enabled)


async def get_wechat_setting(key: str, default: Any = None) -> Any:
    """Read a single field from the stored config."""
    cfg = await load_config()
    return getattr(cfg, key, default)
