"""Push notification configuration.

Stores settings in the ``app_settings`` table as a JSON blob under key
``push_config`` (same pattern as ``wechat_config``).

Supported providers:
- ``bark``  — iOS Bark app (APNs), default server https://api.day.app
- ``ntfy``  — ntfy.sh or self-hosted topic push
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_SETTING_KEY = "push_config"


@dataclass
class PushConfig:
    """Runtime configuration for the push notification channel."""

    enabled: bool = False
    provider: str = "bark"  # bark | ntfy
    # Bark — official or self-hosted server
    bark_server: str = "https://api.day.app"
    bark_device_key: str = ""  # sensitive — never log verbatim
    # ntfy — self-hosted or public instance
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""  # required for ntfy; use something unguessable on public instances
    # Deep link: tapping the notification opens this base URL (the Agent UI)
    deep_link_base: str = ""  # UI base URL opened when the notification is tapped
    # Per-event toggles
    notify_task_done: bool = True
    notify_task_waiting: bool = True  # task waiting for user input/authorization
    notify_schedule_result: bool = True
    notify_email_summary: bool = False
    # Bark options
    sound: str = "minuet"
    time_sensitive: bool = True  # let waiting-for-you notifications break through Focus
    saved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PushConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def masked(self) -> dict[str, Any]:
        """Dict safe for API responses — secrets replaced with a mask."""
        d = self.to_dict()
        if d.get("bark_device_key"):
            d["bark_device_key"] = "•••" + d["bark_device_key"][-4:]
        if d.get("ntfy_topic"):
            d["ntfy_topic"] = "•••" + d["ntfy_topic"][-4:]
        return d


async def load_config() -> PushConfig:
    """Load push config from the ``app_settings`` table."""
    from sqlalchemy import select

    from crabagent.core.database import AppSetting, async_session_factory

    try:
        async with async_session_factory() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.key == _SETTING_KEY))
            row = result.scalar_one_or_none()
            if row and row.value:
                return PushConfig.from_dict(json.loads(row.value))
    except Exception as e:
        logger.warning("Failed to load push config: %s", e)
    return PushConfig()


async def save_config(cfg: PushConfig) -> None:
    """Persist push config to the ``app_settings`` table."""
    from sqlalchemy import select

    from crabagent.core.database import AppSetting, async_session_factory

    cfg.saved_at = datetime.now().isoformat()
    blob = json.dumps(cfg.to_dict(), ensure_ascii=False)

    async with async_session_factory() as db:
        result = await db.execute(select(AppSetting).where(AppSetting.key == _SETTING_KEY))
        row = result.scalar_one_or_none()
        if row:
            row.value = blob
        else:
            db.add(AppSetting(key=_SETTING_KEY, value=blob))
        await db.commit()
    logger.info("Push config saved (enabled=%s, provider=%s)", cfg.enabled, cfg.provider)
