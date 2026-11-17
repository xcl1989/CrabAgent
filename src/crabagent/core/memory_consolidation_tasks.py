"""Process-local background semantic consolidation tasks, isolated by user."""
from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from crabagent.core.memory_batch_merge import semantic_consolidate

logger = logging.getLogger(__name__)
_tasks: dict[int, dict] = {}
_workers: dict[int, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def status(user_id: int) -> dict:
    return deepcopy(_tasks.get(user_id, {"status": "idle"}))


def start(user_id: int) -> dict:
    # No await between the check and registration: atomic within this event loop.
    if user_id in _workers and not _workers[user_id].done():
        return status(user_id)
    job = {"task_id": uuid4().hex, "status": "running", "started_at": _now(),
           "finished_at": None, "progress": {"stage": "starting"}, "result": None}
    _tasks[user_id] = job
    _workers[user_id] = asyncio.create_task(_run(user_id, job))
    return status(user_id)


async def _run(user_id: int, job: dict) -> None:
    def progress(value: dict) -> None:
        job["progress"] = value

    try:
        result = await semantic_consolidate(user_id, progress=progress)
        job["result"] = result
        job["status"] = "completed" if result.get("status") == "ok" else "failed"
    except asyncio.CancelledError:
        job["status"] = "failed"
        job["result"] = {"status": "failed", "reason": "cancelled", "merged": 0}
        raise
    except Exception:
        logger.exception("Semantic consolidation failed for user %s", user_id)
        job["status"] = "failed"
        job["result"] = {"status": "failed", "reason": "internal_error", "merged": 0}
    finally:
        job["finished_at"] = _now()
        job["progress"] = {**job["progress"], "stage": job["status"]}
