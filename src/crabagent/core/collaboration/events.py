"""Record confirmed tool writes in a bound project's activity feed."""

from __future__ import annotations

from pathlib import Path

from crabagent.core.collaboration.write_coordinator import file_version
from crabagent.core.database import (
    CollaborationBinding,
    CollaborationEntry,
    CollaborationProject,
    Conversation,
    async_session_factory,
)


async def record_tool_write(context, tool_name: str, raw_path: str) -> None:
    user_id = context.metadata.get("user_id")
    session_id = context.metadata.get("session_id")
    if not user_id or not session_id or not raw_path:
        return
    workspace = Path(context.workspace).resolve()
    path = Path(raw_path).expanduser()
    path = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(workspace):
        return
    async with async_session_factory() as db:
        binding = await db.get(CollaborationBinding, session_id)
        if not binding or binding.user_id != user_id:
            return
        project = await db.get(CollaborationProject, binding.project_id)
        if not project or project.user_id != user_id or Path(project.workspace).resolve() != workspace:
            return
        rel = str(path.relative_to(workspace))
        db.add(
            CollaborationEntry(
                user_id=user_id,
                project_id=project.id,
                session_id=session_id,
                branch_id=context.metadata.get("branch_id") or "main",
                kind="file_changed",
                content=f"{tool_name}: {rel} (observed version: {file_version(path)})",
                scope=rel,
            )
        )
        await db.commit()


async def record_ui_write(user_id: int, session_id: str, path: Path, operation: str, result_version: str) -> None:
    """Record an authorized UI write only when the session is bound to its workspace."""
    if not session_id:
        return
    from sqlalchemy import select

    async with async_session_factory() as db:
        binding = await db.get(CollaborationBinding, session_id)
        if not binding or binding.user_id != user_id:
            return
        project = await db.get(CollaborationProject, binding.project_id)
        rows = await db.execute(
            select(Conversation).where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
        )
        conversation = rows.scalar_one_or_none()
        if not project or project.user_id != user_id or not conversation or not conversation.workspace:
            return
        workspace = Path(project.workspace).resolve()
        if Path(conversation.workspace).resolve() != workspace:
            return
        resolved = path.resolve()
        if not resolved.is_relative_to(workspace):
            return
        relative = str(resolved.relative_to(workspace))
        db.add(
            CollaborationEntry(
                user_id=user_id,
                project_id=project.id,
                session_id=session_id,
                branch_id=conversation.active_branch or "main",
                kind="file_changed",
                scope=relative,
                content=f"{operation}: {relative} (committed version: {result_version})",
            )
        )
        await db.commit()
