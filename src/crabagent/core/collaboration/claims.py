from __future__ import annotations

from pathlib import Path

from sqlalchemy import and_, or_, select

from crabagent.core.database import CollaborationEntry

PROJECT_TOOLS = frozenset(
    {
        "collaboration_status",
        "collaboration_publish",
        "collaboration_close_claim",
        "collaboration_claim_batch",
        "collaboration_finish_batch",
    }
)


def normalize_scope(workspace: Path, raw: str, *, absolute: bool = False) -> str:
    raw = raw.strip()
    path = Path(raw or ".")
    if path.is_absolute() and not absolute:
        raise ValueError("Scope must be workspace-relative")
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError("Scope must be inside the workspace")
    scope = resolved.relative_to(workspace).as_posix()
    if len(scope) > 2000:
        raise ValueError("Scope is too long")
    return scope


def intention_text(content: str) -> str | None:
    if content.startswith("Automatic managed write: "):
        return None
    if content.startswith("Run batch claim: "):
        from crabagent.core.collaboration.automatic_claims import stale_run_batch_claim

        if stale_run_batch_claim(content):
            return None
    if content.startswith(("Run batch claim: ", "Goal batch claim: ")):
        return content.partition("\n")[2]
    return content


def other_participant(session: str, branch: str):
    return or_(CollaborationEntry.session_id != session, CollaborationEntry.branch_id != branch)


async def overlapping_intentions(db, user_id, project_id, scopes, session, branch, *, descendants=False, limit=5):
    ancestors = {"", "."}
    for scope in scopes:
        path = Path(scope)
        ancestors.update(p.as_posix() for p in (path, *path.parents))
    entry = CollaborationEntry
    match = entry.scope.in_(ancestors)
    if descendants:
        match = (
            True
            if "." in scopes
            else or_(
                match,
                *(entry.scope.startswith(scope + "/", autoescape=True) for scope in scopes),
            )
        )
    rows = await db.scalars(
        select(entry)
        .where(
            and_(
                entry.project_id == project_id,
                entry.user_id == user_id,
                entry.kind == "claim",
                entry.state == "active",
                other_participant(session, branch),
                match,
            )
        )
        .order_by(entry.id.desc())
        .limit(100)
    )
    result = []
    for item in rows:
        if (text := intention_text(item.content)) is not None:
            result.append(
                {
                    "id": item.id,
                    "scope": item.scope or ".",
                    "session": item.session_id,
                    "branch": item.branch_id,
                    "summary": " ".join(text.split())[:240],
                }
            )
            if len(result) >= limit:
                break
    return result


async def competing_claims(context, raw_path: str) -> list[dict]:
    from crabagent.core.database import CollaborationBinding, CollaborationProject, async_session_factory

    user = context.metadata.get("user_id")
    session = context.metadata.get("session_id")
    if not user or not session or not raw_path:
        return []
    workspace = Path(context.workspace).resolve()
    try:
        scope = normalize_scope(workspace, raw_path, absolute=True)
    except (OSError, ValueError, RuntimeError):
        return []
    async with async_session_factory() as db:
        binding = await db.get(CollaborationBinding, session)
        if not binding or binding.user_id != user:
            return []
        project = await db.get(CollaborationProject, binding.project_id)
        if not project or project.user_id != user or project.workspace != str(workspace):
            return []
        return await overlapping_intentions(
            db,
            user,
            project.id,
            [scope],
            session,
            context.metadata.get("branch_id") or "main",
        )
