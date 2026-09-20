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

from crabagent.core.database import AgentRun, Task, TaskEventLog
from crabagent.core.task.events import broadcast_task_event
from crabagent.core.task.status import TaskStatus
from crabagent.core.task.store import get_task as _get_task
from crabagent.core.task.store import update_task as _update_task


async def record_task_event(
    db: AsyncSession,
    user_id: int,
    task_id: int,
    event_type: str,
    title: str,
    detail: str = "",
    run_id: int | None = None,
    data: dict | None = None,
) -> None:
    """Append a user-readable milestone to the task timeline (design 2.7)."""
    db.add(
        TaskEventLog(
            user_id=user_id,
            task_id=task_id,
            run_id=run_id,
            event_type=event_type,
            title=title[:500],
            detail=detail,
            data=data,
        )
    )
    await db.commit()

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
    broadcast_task_event("task_updated", {"task_id": task_id, "status": updated["status"], "run_id": run.id})
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
        # Trusted completion: verify artifacts + checks, then judge the
        # final task status (never trust "run ended" as "task done").
        task_row_result = await db.execute(select(Task).where(Task.id == run.task_id))
        task_row = task_row_result.scalar_one_or_none()
        if task_row:
            from crabagent.core.task.completion import judge_task, refresh_auto_checks

            await refresh_auto_checks(db, run.task_id, user_id, workspace=task_row.workspace, run_id=run_id)
            task_row.active_run_id = None
            task_row.updated_at = now
            if result_summary and not task_row.result_summary:
                task_row.result_summary = result_summary
            await db.commit()
            verdict = await judge_task(db, run.task_id, user_id)
            logger.info("Task %s completion verdict: %s", run.task_id, verdict)
            final_task = await _get_task(db, run.task_id, user_id)

            # Rich card payload: available artifact names + required check counts.
            import os as _os

            from crabagent.core.database import TaskArtifact, TaskCheck

            artifacts = (
                await db.execute(
                    select(TaskArtifact).where(
                        TaskArtifact.task_id == run.task_id,
                        TaskArtifact.status == "available",
                    )
                )
            ).scalars().all()
            artifact_files = [a.name or _os.path.basename(a.path) for a in artifacts if a.path]
            all_checks = (
                await db.execute(select(TaskCheck).where(TaskCheck.task_id == run.task_id))
            ).scalars().all()
            required_checks = [c for c in all_checks if c.required]

            status_labels = {
                "done": "完成",
                "partial": "部分完成",
                "failed": "失败",
                "waiting_user": "等待用户",
            }
            await record_task_event(
                db,
                user_id,
                run.task_id,
                verdict["status"],
                f"任务{status_labels.get(verdict['status'], verdict['status'])}",
                detail=(final_task.get("result_summary") or final_task.get("warning_summary") or "")[:500],
                run_id=run_id,
                data={
                    "verification_status": verdict["verification_status"],
                    "artifacts": verdict["available_artifacts"],
                },
            )
            broadcast_task_event(
                "task_updated",
                {
                    "task_id": run.task_id,
                    "status": verdict["status"],
                    "run_id": run_id,
                    "session_id": run.session_id or "",
                    "verification_status": verdict["verification_status"],
                    "title": final_task["title"],
                    "result_summary": (final_task.get("result_summary") or "")[:300],
                    "warning_summary": (final_task.get("warning_summary") or "")[:300],
                    "files": artifact_files,
                    "checks": (
                        {
                            "passed": sum(1 for c in required_checks if c.status == "passed"),
                            "total": len(required_checks),
                        }
                        if required_checks
                        else None
                    ),
                },
            )
            return final_task
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
    final_task = await _get_task(db, run.task_id, user_id)
    if final_task:
        broadcast_task_event(
            "task_updated",
            {
                "task_id": run.task_id,
                "status": final_task["status"],
                "run_id": run_id,
                "session_id": run.session_id or final_task.get("source_session") or "",
                "title": final_task["title"],
                "result_summary": (final_task.get("result_summary") or "")[:300],
                "warning_summary": (final_task.get("warning_summary") or "")[:300],
                "verification_status": final_task.get("verification_status") or "unverified",
            },
        )
    return final_task


class TaskLifecycleLinker:
    """Drive linked task lifecycle from a conversation's execution events.

    The linker watches the session's event bus: on AGENT_START it attaches
    all open agent-owned tasks created in this session; on TASK_CREATED it
    attaches the just-created task (the initial scan cannot see it because
    task_add runs after AGENT_START); on terminal events it finalizes the
    runs so completion judging and result cards fire. Artifact capture is
    routed to the linked task runs via ``RunRecorder.link_task_run``.
    """

    def __init__(self, user_id: int, session_id: str) -> None:
        self._user_id = user_id
        self._session_id = session_id
        self.run_ids: list[int] = []

    async def _start_linked_run(self, task_id: int, title: str = "") -> None:
        from crabagent.core.database import async_session_factory

        async with async_session_factory() as db:
            _, task_run_id = await start_agent_run(
                db,
                task_id,
                self._user_id,
                agent_name="main",
                session_id=self._session_id,
                task_summary=title,
            )
        self.run_ids.append(task_run_id)

    async def handle_event(self, event, link_run=None, unlink_run=None) -> None:
        from crabagent.core.event import EventType

        if event.type == EventType.AGENT_START:
            self.run_ids.clear()
            try:
                from crabagent.core.database import Task as TaskRow
                from crabagent.core.database import async_session_factory
                from crabagent.core.task.status import OPEN_TASK_STATUSES

                async with async_session_factory() as db:
                    rows = await db.execute(
                        select(TaskRow)
                        .where(
                            TaskRow.user_id == self._user_id,
                            TaskRow.source_session == self._session_id,
                            TaskRow.status.in_(OPEN_TASK_STATUSES),
                            TaskRow.owner_type == "agent",
                            TaskRow.active_run_id.is_(None),
                        )
                        .order_by(TaskRow.id.desc())
                    )
                    open_tasks = [(task.id, task.title) for task in rows.scalars().all()]
                for task_id, title in open_tasks:
                    await self._start_linked_run(task_id, title)
                    if link_run:
                        link_run(self.run_ids[-1])
            except Exception:
                logger.warning("task lifecycle link failed (non-fatal)", exc_info=True)

        elif event.type == EventType.TASK_CREATED:
            # task_add normally runs after AGENT_START, so the initial scan
            # cannot see it. Link it as soon as the tool emits TASK_CREATED.
            try:
                task_id = int(event.data.get("task_id") or 0)
                if task_id:
                    await self._start_linked_run(task_id, str(event.data.get("title") or ""))
                    if link_run:
                        link_run(self.run_ids[-1])
            except Exception:
                logger.warning("new task lifecycle link failed (non-fatal)", exc_info=True)

        elif self.run_ids and event.type in (
            EventType.AGENT_END,
            EventType.AGENT_ERROR,
            EventType.BUDGET_EXHAUSTED,
        ):
            run_ids = self.run_ids[:]
            self.run_ids.clear()
            for run_id in run_ids:
                if unlink_run:
                    unlink_run(run_id)
            if event.type == EventType.AGENT_END:
                run_status, err = "completed", ""
                # AGENT_END carries stats only; the reply text is the last
                # assistant message of this session — use it as the result.
                summary = ""
                try:
                    from crabagent.core.database import Conversation, Message
                    from crabagent.core.database import async_session_factory as _asf

                    async with _asf() as sdb:
                        row = await sdb.execute(
                            select(Message.content)
                            .join(Conversation, Conversation.id == Message.conversation_id)
                            .where(Conversation.session_id == self._session_id, Message.role == "assistant")
                            .order_by(Message.id.desc())
                            .limit(1)
                        )
                        row = row.first()
                        summary = (row[0] or "")[:1000] if row else ""
                except Exception:
                    logger.debug("failed to read last assistant reply", exc_info=True)
            elif event.type == EventType.AGENT_ERROR:
                run_status, summary, err = "failed", "", str(event.data.get("error", ""))
            else:  # BUDGET_EXHAUSTED
                run_status = "interrupted"
                summary = ""
                err = "budget exhausted: " + str(event.data.get("reason", ""))
            try:
                from crabagent.core.database import async_session_factory

                async with async_session_factory() as db:
                    for run_id in run_ids:
                        await finish_agent_run(
                            db,
                            run_id=run_id,
                            user_id=self._user_id,
                            run_status=run_status,
                            result_summary=summary[:1000],
                            error=err[:500],
                        )
            except Exception:
                logger.warning("task lifecycle finish failed (non-fatal)", exc_info=True)


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

    updated = await _update_task(db, task_id, user_id, status=TaskStatus.CANCELLED.value)
    if updated:
        await record_task_event(db, user_id, task_id, "cancelled", "任务已取消", detail=reason[:500])
        broadcast_task_event(
            "task_updated",
            {
                "task_id": task_id,
                "status": updated["status"],
                "title": updated["title"],
                "session_id": updated.get("source_session") or "",
            },
        )
    return updated


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


async def list_task_events(db: AsyncSession, task_id: int, user_id: int, limit: int = 50) -> list[dict]:
    """User-readable task timeline, newest first."""
    result = await db.execute(
        select(TaskEventLog)
        .where(TaskEventLog.task_id == task_id, TaskEventLog.user_id == user_id)
        .order_by(TaskEventLog.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "title": e.title,
            "detail": e.detail,
            "run_id": e.run_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]


async def list_task_runs(db: AsyncSession, task_id: int, user_id: int) -> list[dict]:
    """List all runs belonging to a task, newest first."""
    result = await db.execute(
        select(AgentRun).where(AgentRun.task_id == task_id, AgentRun.user_id == user_id).order_by(AgentRun.id.desc())
    )
    from crabagent.core.database import _run_to_dict

    return [_run_to_dict(r) for r in result.scalars().all()]
