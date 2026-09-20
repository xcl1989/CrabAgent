"""Trusted work system: domain event broadcasting.

Task state changes are broadcast to all live SSE connections so
consumers (TaskPanel, WorkStatusProvider, pet, switcher) refresh without
polling. SSE is only an accelerator: every fact is recoverable via API,
so broadcasting is best-effort and never blocks the state transition.

The serve layer injects the actual broadcaster at startup
(``set_task_event_broadcaster``); the core services stay framework-free.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# fn(event_type: str, data: dict) -> None
_broadcaster: Callable[[str, dict], None] | None = None


def set_task_event_broadcaster(fn: Callable[[str, dict], None] | None) -> None:
    global _broadcaster
    _broadcaster = fn


def broadcast_task_event(event_type: str, data: dict) -> None:
    if _broadcaster is None:
        return
    try:
        _broadcaster(event_type, data)
    except Exception:
        logger.debug("task event broadcast failed (non-fatal)", exc_info=True)
