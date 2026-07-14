from __future__ import annotations

import asyncio
import json
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

    args_summary = json.dumps(args, ensure_ascii=False)
    if len(args_summary) > 200:
        args_summary = args_summary[:200] + "..."

    _pending_confirms[confirm_id] = (future, session_id, tool_name, args_summary)
    await _persist_confirmation(session_id, confirm_id, tool_name, args_summary)

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


async def _persist_confirmation(session_id: str, confirm_id: str, tool_name: str, args_summary: str) -> None:
    """Store the card so session reloads do not depend on the SSE connection."""
    from sqlalchemy import func, select

    from crabagent.core.database import Conversation, Message, async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
        conversation = result.scalar_one_or_none()
        if not conversation:
            return
        max_sequence = await db.scalar(
            select(func.max(Message.sequence)).where(Message.conversation_id == conversation.id)
        )
        db.add(
            Message(
                conversation_id=conversation.id,
                sequence=(max_sequence or 0) + 1,
                role="tool_confirm",
                content=json.dumps({"args_summary": args_summary, "status": "pending"}, ensure_ascii=False),
                name=tool_name,
                tool_call_id=confirm_id,
                branch_id=conversation.active_branch or "main",
            )
        )
        await db.commit()


async def _resolve_persisted_confirmation(confirm_id: str, approved: bool) -> None:
    """Keep completed confirmation cards as an audit trail in session history."""
    from sqlalchemy import select

    from crabagent.core.database import Message, async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(
            select(Message).where(Message.role == "tool_confirm", Message.tool_call_id == confirm_id)
        )
        message = result.scalar_one_or_none()
        if not message:
            return
        try:
            payload = json.loads(message.content or "{}")
        except json.JSONDecodeError:
            payload = {}
        payload["status"] = "approved" if approved else "denied"
        message.content = json.dumps(payload, ensure_ascii=False)
        await db.commit()


def pop_pending(confirm_id: str) -> asyncio.Future[bool] | None:
    entry = _pending_confirms.pop(confirm_id, None)
    return entry[0] if entry else None


def get_pending_confirms_for_session(session_id: str) -> list[dict]:
    """Return all pending (unanswered) tool_confirm requests for a session."""
    result = []
    for confirm_id, (_future, sid, tool_name, args_summary) in _pending_confirms.items():
        if sid != session_id or _future.done():
            continue
        result.append(
            {
                "confirm_id": confirm_id,
                "tool_name": tool_name,
                "args_summary": args_summary,
            }
        )
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
        raise HTTPException(status_code=409, detail="Confirmation request expired; please rerun the operation")

    await _resolve_persisted_confirmation(req.confirm_id, req.approved)
    future.set_result(req.approved)
    return {"status": "ok"}
