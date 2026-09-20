"""Trusted work system: Task ↔ AgentRun orchestration service.

Central place for state transitions between persistent tasks and their
execution runs. API layers, agent tools and the scheduler should go
through this service instead of hand-rolling status updates.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentRun, Task
from crabagent.core.task.status import TaskStatus
from crabagent.core.task.store import get_task as _get_task
from crabagent.core.task.store import update_task as _update_task

logger = logging.getLogger(__name__)

# AgentRun terminal statuses recognized by this service
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"
RUN_STATUS_INTERRUPTED = "interrupted"


async def start_agent_run(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    agent_name: str = "main",
    session_id: str = "",
    model: str = "",
    workspace: str = "",
    phase: str = "",
    task_summary: str = "",
) -> tuple[dict, int]:
    """Mark a task as in_progress and create a linked AgentRun.

    Returns (updated task dict, run_id). Raises LookupError when the task
    does not exist for this user.
    """
    task = await _get_task(db, task_id, user_id)
    if not task:
        raise LookupError(f"Task {task_id} not found")

    run = AgentRun(
        user_id=user_id,
        agent_name=agent_name,
        model=model,
        session_id=session_id,
        task_summary=(task_summary or task["title"])[:200],
        task_id=task_id,
        workspace=workspace or task.get("workspace", ""),
        phase=phase[:200],
        status="running",
        started_at=datetime.datetime.now().timestamp(),
    )
    db.add(run)
    await db.flush()

    now = datetime.datetime.now()
    values = {
        "status": TaskStatus.IN_PROGRESS.value,
        "active_run_id": run.id,
        "last_run_id": run.id,
        "updated_at": now,
    }
    if not task.get("started_at"):
        values["started_at"] = now
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await db.execute(stmt)
    for row in result.scalars().all():
        for k, v in values.items():
            setattr(row, k, v)
    await db.commit()
    await db.refresh(run)

    updated = await _get_task(db, task_id, user_id)
    assert updated is not None
    return updated, run.id


async def finish_agent_run(
    db: AsyncSession,
    run_id: int,
    user_id: int,
    run_status: str,
    result_summary: str = "",
    error: str = "",
    tokens_used: int = 0,
    iterations: int = 0,
) -> dict | None:
    """Finalize a run and propagate the outcome to its task.

    Phase 1 mapping (until the Phase 3 completion service lands):

    - completed → done (record result_summary)
    - failed    → failed
    - cancelled → cancelled (skipped when the task already reached a
      better terminal state such as done)
    - interrupted → partial when there is a usable result_summary,
      otherwise failed

    Returns the updated task dict, or None when the run/task is missing.
    """
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
    run = result.scalar_one_or_none()
    if not run or not run.task_id:
        return None

    task = await _get_task(db, run.task_id, user_id)
    if not task:
        return None

    now = datetime.datetime.now()
    run.status = run_status
    run.finished_at = now.timestamp()
    run.elapsed = max(0.0, now.timestamp() - (run.started_at or now.timestamp()))
    run.tokens_used = tokens_used
    run.iterations = iterations
    if result_summary:
        run.result_summary = result_summary[:1000]
    if error:
        run.error = error[:500]

    task_values: dict = {"active_run_id": None, "updated_at": now}

    if run_status == RUN_STATUS_COMPLETED:
        task_values["status"] = TaskStatus.DONE.value
        task_values["completed_at"] = now
        if result_summary:
            task_values["result_summary"] = result_summary
    elif run_status == RUN_STATUS_FAILED:
        task_values["status"] = TaskStatus.FAILED.value
        task_values["completed_at"] = now
        if error:
            task_values["warning_summary"] = error[:1000]
    elif run_status == RUN_STATUS_CANCELLED:
        if task["status"] not in (TaskStatus.DONE.value, TaskStatus.CANCELLED.value):
            task_values["status"] = TaskStatus.CANCELLED.value
    elif run_status == RUN_STATUS_INTERRUPTED:
        task_values["status"] = (
            TaskStatus.PARTIAL.value if (task.get("result_summary") or result_summary) else TaskStatus.FAILED.value
        )
        task_values["warning_summary"] = "执行被中断：" + (error or "进程退出")[:500]

    task_result = await db.execute(select(Task).where(Task.id == run.task_id))
    task_row = task_result.scalar_one_or_none()
    if task_row:
        for k, v in task_values.items():
            setattr(task_row, k, v)
    await db.commit()

    return await _get_task(db, run.task_id, user_id)


async def cancel_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    reason: str = "",
) -> dict | None:
    """Cancel a task; its active run (if any) is finalized as cancelled."""
    task = await _get_task(db, task_id, user_id)
    if not task:
        return None

    active_run_id = task.get("active_run_id")
    if active_run_id:
        result = await db.execute(select(AgentRun).where(AgentRun.id == active_run_id))
        run = result.scalar_one_or_none()
        if run and run.status == "running":
            now = datetime.datetime.now()
            run.status = RUN_STATUS_CANCELLED
            run.finished_at = now.timestamp()
            run.interrupted_reason = reason[:500] or "user cancelled"

    return await _update_task(db, task_id, user_id, status=TaskStatus.CANCELLED.value)


async def mark_result_viewed(db: AsyncSession, task_id: int, user_id: int) -> dict | None:
    """Record when the user actually opened the task's result."""
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    task = result.scalar_one_or_none()
    if not task:
        return None
    task.result_viewed_at = datetime.datetime.now()
    await db.commit()
    from crabagent.core.task.store import _task_to_dict

    return _task_to_dict(task)


async def list_task_runs(db: AsyncSession, task_id: int, user_id: int) -> list[dict]:
    """List all runs belonging to a task, newest first."""
    result = await db.execute(
        select(AgentRun).where(AgentRun.task_id == task_id, AgentRun.user_id == user_id).order_by(AgentRun.id.desc())
    )
    from crabagent.core.database import _run_to_dict

    return [_run_to_dict(r) for r in result.scalars().all()]
