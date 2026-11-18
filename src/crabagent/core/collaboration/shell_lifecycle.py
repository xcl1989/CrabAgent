"""Retain a shell scope claim while a launched background process remains alive."""

import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)
_TASKS: set[asyncio.Task] = set()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def _watch(context, claim_id: int, pid: int) -> None:
    from crabagent.core.collaboration.automatic_claims import finish

    try:
        while await asyncio.to_thread(_alive, pid):
            await asyncio.sleep(1)
        await finish(context, claim_id, False, "bash")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to monitor background collaboration claim %s", claim_id)


async def track_background_claim(context, claim_id: int, result: str) -> None:
    match = re.search(r"(?:\[background\] PID=|\bPID:\s*)(\d+)", result)
    if not match:
        logger.error("Cannot identify background process for claim %s; retaining claim", claim_id)
        return
    from crabagent.core.collaboration.automatic_claims import persist_background_pid

    pid = int(match.group(1))
    persist_background_pid(claim_id, pid)
    task = asyncio.create_task(_watch(context, claim_id, pid))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
