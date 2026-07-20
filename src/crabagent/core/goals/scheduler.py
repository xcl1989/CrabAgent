from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_CONTINUE_DELAY_SECONDS = 2.0
_tasks: dict[str, asyncio.Task] = {}


def cancel_goal_continuation(session_id: str) -> None:
    task = _tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()


def schedule_goal_continuation(
    session_id: str,
    continuation: Callable[[], Awaitable[None]],
    delay_seconds: float = _CONTINUE_DELAY_SECONDS,
) -> bool:
    """Reserve a single delayed continuation per session."""
    existing = _tasks.get(session_id)
    if existing and not existing.done():
        return False

    async def _run() -> None:
        try:
            await asyncio.sleep(delay_seconds)
            await continuation()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Goal continuation failed for session %s", session_id)
        finally:
            _tasks.pop(session_id, None)

    _tasks[session_id] = asyncio.create_task(_run())
    return True
