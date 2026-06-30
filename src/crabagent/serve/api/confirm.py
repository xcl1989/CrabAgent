from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(tags=["confirm"])

_pending_confirms: dict[str, tuple[asyncio.Future[bool], str, str, str]] = {}
# confirm_id → (future, session_id, tool_name, args_summary)


class ToolConfirmRequest(BaseModel):
    confirm_id: str
    approved: bool


async def request_confirmation(event_bus, session_id: str, tool_name: str, args: dict) -> asyncio.Future[bool]:
    from crabagent.core.event import AgentEvent, EventType

    confirm_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    import json

    args_summary = json.dumps(args, ensure_ascii=False)
    if len(args_summary) > 200:
        args_summary = args_summary[:200] + "..."

    _pending_confirms[confirm_id] = (future, session_id, tool_name, args_summary)

    await event_bus.emit(
        AgentEvent(
            type=EventType.TOOL_CONFIRM_REQUEST,
            data={
                "confirm_id": confirm_id,
                "tool_name": tool_name,
                "args_summary": args_summary,
            },
        )
    )

    return future


def pop_pending(confirm_id: str) -> asyncio.Future[bool] | None:
    entry = _pending_confirms.pop(confirm_id, None)
    return entry[0] if entry else None


def get_pending_confirms_for_session(session_id: str) -> list[dict]:
    """Return all pending (unanswered) tool_confirm requests for a session."""
    result = []
    for confirm_id, (_future, sid, tool_name, args_summary) in _pending_confirms.items():
        if sid != session_id or _future.done():
            continue
        result.append({
            "confirm_id": confirm_id,
            "tool_name": tool_name,
            "args_summary": args_summary,
        })
    return result


@router.post("/sessions/{session_id}/tool-confirm")
async def confirm_tool(
    session_id: str,
    req: ToolConfirmRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from crabagent.serve.services.conversation import get_conversation

    conv = await get_conversation(db, session_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your session")

    future = pop_pending(req.confirm_id)
    if not future or future.done():
        raise HTTPException(status_code=404, detail="Confirmation request not found or expired")

    future.set_result(req.approved)
    return {"status": "ok"}
