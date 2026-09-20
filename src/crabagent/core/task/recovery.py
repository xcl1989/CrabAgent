"""Trusted work system: startup recovery.

Fix zombie state left behind by crashes or restarts:

- ``agent_runs.status = running`` → ``interrupted`` (the process that
  owned the run no longer exists at startup time);
- tasks stuck in ``in_progress`` without a live run → ``partial`` when a
  usable result exists, otherwise ``failed``.

The service never fabricates progress: when precise resumption is not
possible the task explicitly lands in a state that says "restart from a
stage" instead of pretending nothing happened.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentRun, Task
from crabagent.core.task.status import TaskStatus

logger = logging.getLogger(__name__)


async def recover_interrupted_state(db: AsyncSession) -> dict:
    """Run one recovery pass. Idempotent; safe to call at every startup."""
    now = datetime.datetime.now()

    # 1. Zombie runs: everything still marked running belongs to a dead process.
    running_result = await db.execute(select(AgentRun).where(AgentRun.status == "running"))
    zombie_runs = list(running_result.scalars().all())
    affected_task_ids: set[int] = set()
    for run in zombie_runs:
        run.status = "interrupted"
        run.finished_at = now.timestamp()
        run.interrupted_reason = run.interrupted_reason or "应用重启：执行进程已不存在"
        if run.task_id:
            affected_task_ids.add(run.task_id)
    if zombie_runs:
        await db.flush()

    # 2. Tasks that reference a zombie run, or linger in_progress with no
    #    active execution at all.
    stmt = select(Task).where(
        Task.status == TaskStatus.IN_PROGRESS.value,
        Task.active_run_id.isnot(None),
    )
    lingering_result = await db.execute(stmt)
    for task in lingering_result.scalars().all():
        affected_task_ids.add(task.id)

    fixed_runs = len(zombie_runs)
    partial_count = 0
    failed_count = 0

    for task_id in affected_task_ids:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task or task.status != TaskStatus.IN_PROGRESS.value:
            continue
        task.active_run_id = None
        task.updated_at = now
        if task.result_summary:
            task.status = TaskStatus.PARTIAL.value
            partial_count += 1
        else:
            task.status = TaskStatus.FAILED.value
            failed_count += 1

    await db.commit()

    # 3. Expire stale pending TaskRequests (past their TTL).
    expired_requests = 0
    try:
        from crabagent.core.task.request_service import expire_stale_requests

        expired_requests = await expire_stale_requests(db)
    except Exception:
        logger.exception("TaskRequest expiry sweep failed (non-fatal)")

    summary = {
        "interrupted_runs": fixed_runs,
        "partial_tasks": partial_count,
        "failed_tasks": failed_count,
        "expired_requests": expired_requests,
    }
    if fixed_runs or partial_count or failed_count:
        logger.info("Startup recovery: %s", summary)
    return summary
