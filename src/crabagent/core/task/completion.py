"""Trusted work system: verification + completion judgment.

Verification must come from real checks (file stats, render attempts,
command exit codes) — never from model self-confidence. The completion
service then maps verified facts onto the task's final status:

    pending blocking request → waiting_user
    required checks passed + usable artifact → done
    usable artifact but checks unmet      → partial
    no usable artifact                    → failed
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Task, TaskArtifact, TaskCheck, TaskRequest
from crabagent.core.task.status import TaskStatus

logger = logging.getLogger(__name__)

AUTO_CHECK_TITLE_PREFIX = "成果文件可用:"


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def verify_file(path: str, workspace: str = "") -> dict:
    """Minimal generic file verification: exists, non-empty, readable, in-bounds."""
    evidence: list[str] = []
    problems: list[str] = []

    p = Path(path)
    if not p.exists():
        return {"status": "failed", "evidence": f"文件不存在: {path}", "data": {"path": path}}
    if not p.is_file():
        return {"status": "failed", "evidence": f"不是普通文件: {path}", "data": {"path": path}}

    size = p.stat().st_size
    if size == 0:
        problems.append("文件为空")
    else:
        evidence.append(f"大小 {size} 字节")

    try:
        with open(p, "rb") as fh:
            fh.read(1)
        evidence.append("可读取")
    except OSError as e:
        problems.append(f"不可读取: {e}")

    if workspace:
        ws = Path(workspace).resolve()
        try:
            p.resolve().relative_to(ws)
            evidence.append("位于工作区内")
        except ValueError:
            problems.append("位于工作区边界之外")

    if problems:
        status = "failed" if any("不存在" in x or "不可读取" in x for x in problems) else "warning"
        return {"status": status, "evidence": "; ".join(problems), "data": {"path": path, "size": size}}
    return {"status": "passed", "evidence": "；".join(evidence), "data": {"path": path, "size": size}}


async def refresh_auto_checks(
    db: AsyncSession,
    task_id: int,
    user_id: int,
    workspace: str = "",
    run_id: int | None = None,
) -> list[dict]:
    """Re-verify file artifacts and replace the auto-generated checks."""
    # Drop previous auto checks (manual acceptance criteria stay untouched).
    await db.execute(
        delete(TaskCheck).where(
            TaskCheck.task_id == task_id,
            TaskCheck.title.like(f"{AUTO_CHECK_TITLE_PREFIX}%"),
        )
    )

    result = await db.execute(
        select(TaskArtifact).where(
            TaskArtifact.task_id == task_id,
            TaskArtifact.user_id == user_id,
            TaskArtifact.status != "superseded",
        )
    )
    artifacts = list(result.scalars().all())

    checks: list[dict] = []
    for position, artifact in enumerate(artifacts):
        if not artifact.path:
            continue
        outcome = verify_file(artifact.path, workspace)
        db.add(
            TaskCheck(
                user_id=user_id,
                task_id=task_id,
                run_id=run_id,
                title=f"成果文件可用: {artifact.name or artifact.path}",
                required=True,
                status=outcome["status"],
                evidence=outcome["evidence"],
                evidence_data={"auto": True, **(outcome.get("data") or {})},
                position=position,
                verified_at=_now(),
            )
        )
        checks.append(
            {
                "artifact_id": artifact.id,
                "path": artifact.path,
                "status": outcome["status"],
                "evidence": outcome["evidence"],
            }
        )
    await db.commit()
    return checks


async def judge_task(db: AsyncSession, task_id: int, user_id: int) -> dict:
    """Collect facts and decide the task's final status. Pure DB judgment."""
    task = (await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))).scalar_one_or_none()
    if not task:
        raise LookupError(f"Task {task_id} not found")

    artifacts = (
        (
            await db.execute(
                select(TaskArtifact).where(
                    TaskArtifact.task_id == task_id,
                    TaskArtifact.status != "superseded",
                )
            )
        )
        .scalars()
        .all()
    )
    available_artifacts = [a for a in artifacts if a.status == "available"]
    file_artifacts = [a for a in available_artifacts if a.path]

    checks = (await db.execute(select(TaskCheck).where(TaskCheck.task_id == task_id))).scalars().all()
    required = [c for c in checks if c.required]
    required_passed = all(c.status == "passed" for c in required) if required else None

    pending_requests = (
        (await db.execute(select(TaskRequest).where(TaskRequest.task_id == task_id, TaskRequest.status == "pending")))
        .scalars()
        .all()
    )

    if pending_requests:
        final_status = TaskStatus.WAITING_USER.value
    elif required_passed is False:
        # Required acceptance criteria failed → never done.
        final_status = TaskStatus.PARTIAL.value
    elif file_artifacts:
        # Usable file artifacts + no failing required check.
        final_status = TaskStatus.DONE.value
    elif task.result_summary:
        # No-file task: an explicit result summary counts as the main result.
        final_status = TaskStatus.DONE.value
    elif required_passed is True:
        # No artifacts, no summary, but all required checks passed (e.g. checks-only task).
        final_status = TaskStatus.DONE.value
    elif required_passed is None:
        # Nothing verified and nothing produced.
        final_status = TaskStatus.FAILED.value
    else:
        final_status = TaskStatus.FAILED.value

    # Overall verification status from check outcomes.
    if not checks:
        verification = "unverified"
    elif all(c.status == "passed" for c in checks):
        verification = "passed"
    elif any(c.status == "failed" for c in checks):
        verification = "failed"
    else:
        verification = "partial"

    now = _now()
    task.status = final_status
    task.verification_status = verification
    task.updated_at = now
    if final_status in (TaskStatus.DONE.value, TaskStatus.PARTIAL.value, TaskStatus.FAILED.value):
        task.completed_at = task.completed_at or now
    await db.commit()

    return {
        "status": final_status,
        "verification_status": verification,
        "available_artifacts": len(available_artifacts),
        "required_checks": len(required),
        "required_checks_passed": required_passed,
        "pending_requests": len(pending_requests),
    }
