from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/work/attention", tags=["work-attention"])


@router.get("/summary")
async def attention_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unified attention summary: what needs the user right now, sorted by priority."""
    from crabagent.core.task.attention import get_attention_summary

    return await get_attention_summary(db, user.id)


@router.get("/by-workspace")
async def attention_by_workspace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Highest-priority attention state per workspace (switcher badges)."""
    from crabagent.core.task.attention import get_attention_by_workspace

    return {"workspaces": await get_attention_by_workspace(db, user.id)}


@router.get("/by-session")
async def attention_by_session(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pending attention items grouped by their source session."""
    from sqlalchemy import select

    from crabagent.core.database import TaskRequest
    from crabagent.core.task.attention import get_attention_summary

    summary = await get_attention_summary(db, user.id)

    session_keys: dict[str, dict] = {}
    for kind, items in summary["groups"].items():
        for item in items:
            target = item.get("target") or {}
            session_id = target.get("session_id")
            if not session_id:
                # task-linked items resolve the session through the request table
                continue
            entry = session_keys.setdefault(session_id, {"session_id": session_id, "priority": 99, "items": []})
            entry["priority"] = min(entry["priority"], item["priority"])
            entry["items"].append(item)

    # Also group pending requests by session directly (source of truth).
    rows = await db.execute(
        select(TaskRequest.session_id).where(TaskRequest.user_id == user.id, TaskRequest.status == "pending")
    )
    for (session_id,) in rows.all():
        if session_id and session_id not in session_keys:
            session_keys[session_id] = {"session_id": session_id, "priority": 0, "items": []}

    return {
        "sessions": sorted(session_keys.values(), key=lambda e: e["priority"]),
    }
