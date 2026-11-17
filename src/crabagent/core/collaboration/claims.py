from __future__ import annotations

from sqlalchemy import select

from crabagent.core.database import CollaborationEntry


async def find_overlapping_claims(db, user_id: int, project_id: int, scope: str) -> list[int]:
    wanted = scope.strip().strip("/")
    if not wanted:
        return []
    rows = await db.execute(
        select(CollaborationEntry).where(
            CollaborationEntry.project_id == project_id,
            CollaborationEntry.user_id == user_id,
            CollaborationEntry.kind == "claim",
            CollaborationEntry.state == "active",
        )
    )
    overlaps = []
    for entry in rows.scalars():
        existing = entry.scope.strip().strip("/")
        if existing and (existing == wanted or existing.startswith(wanted + "/") or wanted.startswith(existing + "/")):
            overlaps.append(entry.id)
    return overlaps


async def competing_claims(context, raw_path: str) -> list[dict]:
    """Return other participants' active overlapping claims for a workspace file."""
    from pathlib import Path

    from crabagent.core.database import CollaborationBinding, CollaborationProject, async_session_factory

    user_id = context.metadata.get("user_id")
    session_id = context.metadata.get("session_id")
    if not user_id or not session_id or not raw_path:
        return []
    workspace = Path(context.workspace).resolve()
    path = Path(raw_path).expanduser()
    path = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(workspace):
        return []
    scope = str(path.relative_to(workspace))
    async with async_session_factory() as db:
        binding = await db.get(CollaborationBinding, session_id)
        if not binding or binding.user_id != user_id:
            return []
        project = await db.get(CollaborationProject, binding.project_id)
        if not project or project.user_id != user_id or Path(project.workspace).resolve() != workspace:
            return []
        ids = await find_overlapping_claims(db, user_id, project.id, scope)
        if not ids:
            return []
        rows = await db.execute(select(CollaborationEntry).where(CollaborationEntry.id.in_(ids)))
        branch = context.metadata.get("branch_id") or "main"
        return [
            {"id": entry.id, "scope": entry.scope, "session": entry.session_id, "branch": entry.branch_id}
            for entry in rows.scalars()
            if entry.session_id != session_id or entry.branch_id != branch
        ]
