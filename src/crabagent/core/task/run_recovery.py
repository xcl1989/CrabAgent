"""Trusted work system: run-level recovery.

Molts are recovery points; this service binds them to runs so users can
answer "how do I undo THIS execution?" without hand-picking molt ids.

Rollback conflict detection compares three versions of each file:

1. pre-run snapshot content (the restore target),
2. content as of the end of this run,
3. current content.

Because version 1 does not snapshot end-of-run content, a later molt
touching the same file is used as the evidence of "modified after this
run": in that case a direct overwrite is refused unless the user forces
it.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentRun, RunMolt, Task
from crabagent.core.task.status import TaskStatus

logger = logging.getLogger(__name__)


def _now() -> datetime.datetime:
    return datetime.datetime.now()


async def link_molt_to_run(db: AsyncSession, run_id: int, molt_id: str, scope: str = "run") -> None:
    """Record that a molt protects a specific run (idempotent per pair)."""
    existing = await db.execute(select(RunMolt).where(RunMolt.run_id == run_id, RunMolt.molt_id == molt_id))
    if existing.scalar_one_or_none():
        return
    count = len((await db.execute(select(RunMolt).where(RunMolt.run_id == run_id))).scalars().all())
    db.add(RunMolt(run_id=run_id, molt_id=molt_id, sequence=count, scope=scope))
    await db.commit()


async def link_active_run_molt(db: AsyncSession, session_id: str, molt_id: str) -> int | None:
    """Best-effort: link a freshly created molt to the session's running run."""
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.session_id == session_id, AgentRun.status == "running")
        .order_by(AgentRun.id.desc())
        .limit(1)
    )
    run = result.scalars().first()
    if not run:
        return None
    await link_molt_to_run(db, run.id, molt_id)
    return run.id


async def list_run_molts(db: AsyncSession, run_id: int) -> list[dict]:
    rows = (
        (await db.execute(select(RunMolt).where(RunMolt.run_id == run_id).order_by(RunMolt.sequence))).scalars().all()
    )
    return [
        {
            "run_id": r.run_id,
            "molt_id": r.molt_id,
            "sequence": r.sequence,
            "scope": r.scope,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def _resolve_workspace(db: AsyncSession, task_id: int) -> Path:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    return Path(task.workspace) if task and task.workspace else Path.cwd()


async def list_run_changes(db: AsyncSession, task_id: int, run_id: int, user_id: int) -> dict:
    """Compare each run-molt's pre-run snapshot against the current file."""
    from crabagent.core.molt.store import get_current_content, get_snapshot_content, list_molt_files

    run = (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
    ).scalar_one_or_none()
    if not run:
        raise LookupError(f"Run {run_id} not found")

    workspace = await _resolve_workspace(db, task_id)
    molt_links = await list_run_molts(db, run_id)

    changes: list[dict] = []
    for link in molt_links:
        for rel in await list_molt_files(link["molt_id"], workspace):
            before = get_snapshot_content(link["molt_id"], rel, workspace)
            current = get_current_content(workspace, rel)
            if before == current:
                status = "unchanged"
            elif not (workspace / rel).exists():
                status = "created"  # not in snapshot, present now → created during/after run
            else:
                status = "modified"
            changes.append(
                {
                    "file": rel,
                    "molt_id": link["molt_id"],
                    "status": status,
                    "changed": status != "unchanged",
                }
            )
    return {
        "run_id": run_id,
        "task_id": task_id,
        "status": run.status,
        "molt_count": len(molt_links),
        "changes": changes,
    }


async def rollback_run(
    db: AsyncSession,
    task_id: int,
    run_id: int,
    user_id: int,
    force: bool = False,
) -> dict:
    """Undo one run by restoring its pre-run snapshot content.

    Refuses to overwrite files that were modified after this run (a later
    molt covers them) unless ``force`` is set.
    """
    from crabagent.core.molt.store import get_current_content, get_snapshot_content, list_molt_files

    run = (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))
    ).scalar_one_or_none()
    if not run:
        raise LookupError(f"Run {run_id} not found")

    workspace = await _resolve_workspace(db, task_id)
    molt_links = await list_run_molts(db, run_id)
    if not molt_links:
        return {"status": "no_recovery_point", "restored": [], "conflicts": []}

    # Evidence of later modifications: molts of LATER runs touching the same files.
    later_run_ids = set(
        (await db.execute(select(AgentRun.id).where(AgentRun.task_id == task_id, AgentRun.id > run_id)))
        .scalars()
        .all()
    )
    later_files: set[str] = set()
    for later_run_id in later_run_ids:
        for link in await list_run_molts(db, later_run_id):
            later_files.update(await list_molt_files(link["molt_id"], workspace))

    conflicts: list[dict] = []
    restored: list[str] = []
    skipped_unchanged = 0

    for link in molt_links:
        for rel in await list_molt_files(link["molt_id"], workspace):
            before = get_snapshot_content(link["molt_id"], rel, workspace)
            current = get_current_content(workspace, rel)
            if before == current:
                skipped_unchanged += 1
                continue
            if rel in later_files and not force:
                conflicts.append(
                    {
                        "file": rel,
                        "reason": "该文件在本 Run 之后又被修改（存在更晚的恢复点），需 force 确认或先比较差异",
                    }
                )
                continue
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if before == "" and not (workspace / rel).exists():
                continue
            if before == "":
                # File did not exist before the run → undo means removing it.
                if target.exists():
                    target.unlink()
                restored.append(rel)
            else:
                target.write_text(before, encoding="utf-8")
                restored.append(rel)

    result = {
        "status": "conflict" if conflicts and not restored else ("ok" if restored else "unchanged"),
        "restored": restored,
        "conflicts": conflicts,
        "skipped_unchanged": skipped_unchanged,
        "forced": force,
    }

    # Bookkeeping: the run is marked rolled back; the task keeps its status
    # but gains a warning so the user can see the undo happened.
    if restored or force:
        run.interrupted_reason = (run.interrupted_reason or "") + f" | rolled back at {_now():%Y-%m-%d %H:%M}"
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if task:
            note = f"Run {run_id} 已回滚（{len(restored)} 个文件恢复）"
            task.warning_summary = (task.warning_summary + "\n" + note).strip() if task.warning_summary else note
        await db.commit()

    return result


async def retry_task(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    agent_name: str = "main",
    session_id: str = "",
) -> tuple[dict, int]:
    """Retry from a failed/partial state: a NEW run, history untouched."""
    from crabagent.core.task import service as task_service
    from crabagent.core.task.store import get_task

    task = await get_task(db, task_id, user_id)
    if not task:
        raise LookupError(f"Task {task_id} not found")
    if task["status"] not in (
        TaskStatus.FAILED.value,
        TaskStatus.PARTIAL.value,
        TaskStatus.CANCELLED.value,
    ):
        raise ValueError(f"Task {task_id} is {task['status']}; only failed/partial/cancelled tasks can retry")

    return await task_service.start_agent_run(
        db,
        task_id,
        user_id,
        agent_name=agent_name,
        session_id=session_id or (task.get("source_session") or ""),
    )
