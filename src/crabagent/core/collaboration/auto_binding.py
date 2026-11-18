from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, text, update

from crabagent.core.database import CollaborationBinding, CollaborationEntry, CollaborationProject, Conversation


def normalize_workspace(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    try:
        path = Path(value).expanduser().resolve()
        return str(path) if path.is_dir() else None
    except (OSError, RuntimeError, ValueError):
        return None


async def _binding_state(db, user_id: int, session_id: str):
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.session_id == session_id,
            Conversation.user_id == user_id,
        )
    )
    if not conversation:
        return None, None, None
    workspace = None if conversation.collaboration_disabled else normalize_workspace(conversation.workspace)
    binding = await db.get(CollaborationBinding, session_id)
    if binding and binding.user_id != user_id:
        return None, None, None
    project = await db.get(CollaborationProject, binding.project_id) if binding else None
    if project and project.user_id != user_id:
        project = None
    return workspace, binding, project


async def ensure_session_binding(db, user_id: int, session_id: str) -> int | None:
    """Only acquire the SQLite writer lock when the binding actually needs changing."""
    workspace, binding, project = await _binding_state(db, user_id, session_id)
    if project and project.workspace == workspace:
        return project.id
    if not workspace and not binding:
        return None
    await db.rollback()
    await db.execute(text("BEGIN IMMEDIATE"))
    try:
        workspace, binding, project = await _binding_state(db, user_id, session_id)
        if project and project.workspace == workspace:
            await db.commit()
            return project.id
        project = None
        if workspace:
            project = await db.scalar(
                select(CollaborationProject).where(
                    CollaborationProject.user_id == user_id,
                    CollaborationProject.workspace == workspace,
                )
            )
            if not project:
                project = CollaborationProject(
                    user_id=user_id,
                    workspace=workspace,
                    name=Path(workspace).name[:200] or workspace[:200],
                )
                db.add(project)
                await db.flush()
        if binding:
            await db.execute(
                update(CollaborationEntry)
                .where(
                    CollaborationEntry.user_id == user_id,
                    CollaborationEntry.project_id == binding.project_id,
                    CollaborationEntry.session_id == session_id,
                    CollaborationEntry.kind == "claim",
                    CollaborationEntry.state == "active",
                )
                .values(state="closed")
            )
            if project:
                binding.project_id = project.id
            else:
                await db.delete(binding)
        elif project:
            db.add(CollaborationBinding(session_id=session_id, user_id=user_id, project_id=project.id))
        await db.commit()
        return project.id if project else None
    except BaseException:
        await db.rollback()
        raise
