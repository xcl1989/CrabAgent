"""Persist bounded browser execution facts, independent of renderer-provided events."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from crabagent.core.database import BrowserTask, BrowserTaskEvent, async_session_factory

logger = logging.getLogger(__name__)


def safe_origin(url: str) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        return f"{parts.scheme}://{parts.hostname[:200]}"
    except ValueError:
        return ""


async def record_browser_event(
    context: Any,
    event_type: str,
    *,
    action: str = "",
    decision: str = "",
    observation_id: str = "",
    url: str = "",
    started: float | None = None,
) -> None:
    """Only allowlist-derived fields reach the database; no page or input content."""
    session_id = context.metadata.get("session_id") if context else None
    user_id = context.metadata.get("user_id") if context else None
    if not session_id or not user_id:
        return
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(BrowserTask)
                .where(
                    BrowserTask.session_id == session_id,
                    BrowserTask.user_id == user_id,
                    BrowserTask.status.in_(("running", "waiting_for_user", "paused")),
                )
                .order_by(BrowserTask.id.desc())
                .limit(1)
            )
            task = result.scalar_one_or_none()
            if task is None:
                return
            data = {
                "runtime": "electron-browser",
                "action": action[:40],
                "decision": decision[:30],
                "observation_id": observation_id[:64],
                "origin": safe_origin(url),
                "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)) if started else 0,
            }
            db.add(
                BrowserTaskEvent(
                    task_id=task.id,
                    event_type=event_type,
                    detail=action[:40],
                    risk="high" if decision == "confirmation_required" else "low",
                    data=data,
                )
            )
            await db.commit()
    except Exception:
        logger.warning("Failed to persist browser audit event", exc_info=True)
