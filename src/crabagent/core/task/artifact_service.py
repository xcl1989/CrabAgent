"""Trusted work system: artifact capture service.

Artifacts are registered automatically from real tool results — never
hand-written by the model. For the same task+path, a new registration
supersedes the previous version (version += 1) so stale approvals die
when the underlying file changes.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentRun, TaskArtifact

logger = logging.getLogger(__name__)

# tool name → (action, artifact_type)
TOOL_ARTIFACT_MAP: dict[str, tuple[str, str]] = {
    "write": ("created", "file"),
    "edit": ("modified", "file"),
    "office_create": ("created", "file"),
    "office_edit": ("modified", "file"),
    "office_batch_edit": ("modified", "file"),
    "image_generate": ("created", "file"),
    "image_edit": ("modified", "file"),
}

# Substrings that mark a tool result as failed (best-effort guard).
_FAILURE_MARKERS = ("创建失败", "修改失败", "失败:", "Failed", "Error:", "error:", "not found", "File not found")


def _artifact_to_dict(a: TaskArtifact) -> dict:
    return {
        "id": a.id,
        "user_id": a.user_id,
        "task_id": a.task_id,
        "run_id": a.run_id,
        "artifact_type": a.artifact_type,
        "name": a.name,
        "path": a.path,
        "mime_type": a.mime_type,
        "action": a.action,
        "status": a.status,
        "external_id": a.external_id,
        "version": a.version,
        "metadata": a.metadata_,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or ""


def extract_tool_paths(tool_name: str, args: dict, result: object) -> list[tuple[str, str]]:
    """Extract (abs_or_relative_path, user_visible_name) from a tool call.

    Only real values from tool arguments/results are used. Returns an
    empty list when the tool is not an artifact producer.
    """
    if tool_name not in TOOL_ARTIFACT_MAP:
        return []
    path = str(args.get("file_path") or "").strip()
    if path:
        return [(path, os.path.basename(path))]
    if tool_name == "image_generate":
        # image_generate returns JSON with a "files" array of saved paths.
        try:
            import json

            payload = json.loads(str(result))
            files = payload.get("files") or []
            return [(f, os.path.basename(f)) for f in files if isinstance(f, str) and f]
        except Exception:
            return []
    return []


def tool_result_failed(result: object) -> bool:
    text = str(result or "")
    if not text:
        return True
    head = text[:300]
    return any(marker in head for marker in _FAILURE_MARKERS)


async def register_artifact(
    db: AsyncSession,
    user_id: int,
    task_id: int,
    run_id: int | None,
    artifact_type: str,
    name: str,
    path: str = "",
    action: str = "created",
    external_id: str = "",
    metadata: dict | None = None,
) -> dict:
    """Register (or version-bump) an artifact for a task.

    Same task + same normalized path → supersede the old row and bump the
    version, so authorization tied to an older version becomes invalid.
    """
    normalized = str(Path(path)) if path else ""
    existing = None
    if normalized:
        result = await db.execute(
            select(TaskArtifact).where(
                TaskArtifact.task_id == task_id,
                TaskArtifact.path == normalized,
                TaskArtifact.status != "superseded",
            )
        )
        existing = result.scalars().first()

    status = "available"
    if path:
        # A missing file is recorded as-is — the completion service decides
        # whether the task can still be done; we never hide the fact.
        status = "available" if os.path.isfile(path) else "missing"

    if existing:
        existing.status = "superseded"
        existing.updated_at = existing.updated_at  # trigger onupdate
        row = TaskArtifact(
            user_id=user_id,
            task_id=task_id,
            run_id=run_id,
            artifact_type=artifact_type,
            name=name or existing.name,
            path=normalized,
            mime_type=_guess_mime(normalized),
            action=action,
            status=status,
            external_id=external_id,
            version=existing.version + 1,
            metadata_=metadata,
        )
    else:
        row = TaskArtifact(
            user_id=user_id,
            task_id=task_id,
            run_id=run_id,
            artifact_type=artifact_type,
            name=name,
            path=normalized,
            mime_type=_guess_mime(normalized),
            action=action,
            status=status,
            external_id=external_id,
            version=1,
            metadata_=metadata,
        )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _artifact_to_dict(row)


async def register_artifact_from_tool(
    run_id: int,
    tool_name: str,
    args: dict,
    result: object,
) -> dict | None:
    """Capture an artifact from a completed tool call.

    Resolves the owning task through the run; silently skips when the run
    has no task (regular chat usage) or the tool produced nothing.
    """
    if tool_name not in TOOL_ARTIFACT_MAP or tool_result_failed(result):
        return None
    paths = extract_tool_paths(tool_name, args or {}, result)
    if not paths:
        return None

    from crabagent.core.database import async_session_factory

    action, artifact_type = TOOL_ARTIFACT_MAP[tool_name]
    async with async_session_factory() as db:
        run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
        if not run or not run.task_id:
            return None
        registered = None
        for path, name in paths:
            registered = await register_artifact(
                db,
                user_id=run.user_id,
                task_id=run.task_id,
                run_id=run_id,
                artifact_type=artifact_type,
                name=name,
                path=path,
                action=action,
                metadata={"tool": tool_name},
            )
        return registered


async def list_artifacts(db: AsyncSession, task_id: int, user_id: int) -> list[dict]:
    result = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == task_id, TaskArtifact.user_id == user_id)
        .order_by(TaskArtifact.id)
    )
    return [_artifact_to_dict(a) for a in result.scalars().all()]


async def current_artifact_version(db: AsyncSession, task_id: int, path: str) -> int:
    """Latest non-superseded version for a path (used by authorization guards)."""
    normalized = str(Path(path))
    result = await db.execute(
        select(TaskArtifact)
        .where(
            TaskArtifact.task_id == task_id,
            TaskArtifact.path == normalized,
            TaskArtifact.status != "superseded",
        )
        .order_by(TaskArtifact.version.desc())
        .limit(1)
    )
    row = result.scalars().first()
    return row.version if row else 0
