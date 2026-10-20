"""Push notification channel (Bark / ntfy).

Provides:
- PushNotification — facade for sending (mirrors WeChatNotification style)
- notify_task_event — hook wired into the task event broadcaster so terminal
  and waiting_user task transitions push to the phone automatically
- Config lives in the ``app_settings`` table under key ``push_config``.

This channel is independent of WeChat: both can be enabled at the same time
and are dispatched in parallel by the notification router.
"""

from __future__ import annotations

import asyncio
import logging
import time

from crabagent.core.push.client import PushError, PushPayload, send_bark, send_ntfy
from crabagent.core.push.config import PushConfig, load_config, save_config

logger = logging.getLogger(__name__)

__all__ = [
    "PushConfig",
    "PushNotification",
    "PushError",
    "PushPayload",
    "load_config",
    "save_config",
    "notify_task_event",
]

# (task_id, status) -> last push timestamp; in-memory, best-effort dedup.
_recent: dict[tuple[str, str], float] = {}
_DEDUP_WINDOW = 600.0  # 10 minutes


class PushNotification:
    """Send push notifications via the configured provider (Bark/ntfy)."""

    @staticmethod
    async def send(
        title: str,
        body: str = "",
        url: str = "",
        category: str = "",
    ) -> bool:
        """Send one notification. Returns ``False`` when disabled/misconfigured.

        Never raises: failures are logged so callers can fire-and-forget.
        """
        cfg = await load_config()
        if not cfg.enabled:
            return False

        # Per-category toggles
        if category == "task_done" and not cfg.notify_task_done:
            return False
        if category == "task_waiting" and not cfg.notify_task_waiting:
            return False
        if category == "scheduled_task" and not cfg.notify_schedule_result:
            return False
        if category == "email" and not cfg.notify_email_summary:
            return False

        payload = PushPayload(
            title=title,
            body=body,
            url=url or cfg.deep_link_base,
            category=category,
            sound=cfg.sound,
            time_sensitive=cfg.time_sensitive,
        )
        try:
            if cfg.provider == "ntfy":
                await send_ntfy(cfg.ntfy_server, cfg.ntfy_topic, payload)
            else:
                await send_bark(cfg.bark_server, cfg.bark_device_key, payload)
        except PushError as e:
            logger.warning("[PushNotify] %s send failed: %s", cfg.provider, e)
            return False
        logger.info("[PushNotify] sent via %s: category=%s, title=%s", cfg.provider, category, title)
        return True

    @staticmethod
    async def send_task_done(task: dict) -> bool:
        """Push a task terminal-state notification (done/partial/failed/cancelled)."""
        status = task.get("status", "")
        emoji = {"done": "✅", "partial": "🟡", "failed": "❌", "cancelled": "⚪️"}.get(status, "🔔")
        label = {"done": "完成", "partial": "部分完成", "failed": "失败", "cancelled": "已取消"}.get(status, status)
        title = f"{emoji} 任务{label}"
        body = task.get("title", "未知任务")
        summary = task.get("result_summary") or task.get("warning_summary") or ""
        if summary:
            body += f"\n{summary[:300]}"
        return await PushNotification.send(title, body, category="task_done")

    @staticmethod
    async def send_task_waiting(task: dict) -> bool:
        """Push a time-sensitive 'task is waiting for you' notification."""
        title = "⏸ 任务在等你"
        body = task.get("title", "未知任务")
        return await PushNotification.send(title, body, category="task_waiting")


def notify_task_event(event_type: str, data: dict) -> None:
    """Fire-and-forget push for task domain events.

    Designed to be chained after the SSE broadcaster in
    ``serve/app.py::_broadcast_task_event``. Sync on purpose (the broadcaster
    interface is sync); the actual network call is scheduled as a task.

    Pushes only state transitions users care about:
    - terminal states (done/partial/failed/cancelled) → task_done push
    - waiting_user → time-sensitive "waiting for you" push
    Repeats of the same (task_id, status) within 10 minutes are dropped so the
    completion-service's richer re-broadcast does not double-push.
    """
    if event_type != "task_updated":
        return
    status = str(data.get("status") or "")
    task_id = str(data.get("task_id") or "")
    if status not in ("done", "partial", "failed", "cancelled", "waiting_user") or not task_id:
        return

    now = time.monotonic()
    key = (task_id, status)
    last = _recent.get(key)
    if last and now - last < _DEDUP_WINDOW:
        return
    _recent[key] = now
    # Prune old entries occasionally
    if len(_recent) > 256:
        cutoff = now - _DEDUP_WINDOW
        for k in [k for k, ts in _recent.items() if ts < cutoff]:
            _recent.pop(k, None)

    async def _run() -> None:
        try:
            if status == "waiting_user":
                await PushNotification.send_task_waiting(data)
            else:
                await PushNotification.send_task_done(data)
        except Exception:
            logger.debug("task push failed (non-fatal)", exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        # No running loop (shouldn't happen — broadcaster runs inside serve loop)
        logger.debug("notify_task_event called without running loop; dropped")
