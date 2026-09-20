from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(tags=["confirm"])

logger = logging.getLogger(__name__)

CONFIRM_TTL_SECONDS = 120

_pending_confirms: dict[str, tuple[asyncio.Future[bool], str, str, str]] = {}
# confirm_id → (future, session_id, tool_name, args_summary)


class ToolConfirmRequest(BaseModel):
    confirm_id: str
    approved: bool


async def request_confirmation(
    event_bus, session_id: str, tool_name: str, args: dict, user_id: int = 1
) -> asyncio.Future[bool]:
    from crabagent.core.event import AgentEvent, EventType

    confirm_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    args_summary = json.dumps(args, ensure_ascii=False)
    if len(args_summary) > 200:
        args_summary = args_summary[:200] + "..."

    _pending_confirms[confirm_id] = (future, session_id, tool_name, args_summary)
    await _persist_confirmation(session_id, confirm_id, tool_name, args_summary)

    # Trusted work system: also persist a TaskRequest so the approval
    # survives restarts. The live Future above is only a bridge.
    try:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.request_service import create_request, register_live_future

        async with async_session_factory() as db:
            await create_request(
                db,
                user_id=user_id,
                request_type="approval",
                request_key=confirm_id,
                title=f"确认执行 {tool_name}",
                session_id=session_id,
                operation=f"tool:{tool_name}",
                question="是否允许执行该操作？",
                risk_level="high",
                display_payload={"args_summary": args_summary},
                resource_version=args_summary[:200],
                expires_at=datetime.datetime.now() + datetime.timedelta(seconds=CONFIRM_TTL_SECONDS + 10),
            )
        register_live_future(confirm_id, future)
    except Exception:
        logger.exception("Failed to persist TaskRequest for confirm %s", confirm_id)

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


@router.get("/sessions/{session_id}/pending-confirms")
async def list_pending_confirms(
    session_id: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from crabagent.serve.services.conversation import get_conversation

    conv = await get_conversation(db, session_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your session")
    return {"confirms": get_pending_confirms_for_session(session_id)}


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
        # Fall back to the persistent TaskRequest (restart-safe decisions).
        from crabagent.core.task.request_service import decide_request

        try:
            payload = await decide_request(db, req.confirm_id, user.id, "approve" if req.approved else "reject")
        except LookupError:
            raise HTTPException(status_code=409, detail="Confirmation request expired; please rerun the operation")
        if payload["status"] == "expired":
            raise HTTPException(status_code=409, detail="Confirmation request expired; please rerun the operation")
        return {"status": "ok", "future_resolved": payload.get("future_resolved", False)}

    # Live bridge: the persistent service records the decision exactly once
    # and resolves the Future through the live-future registry.
    from crabagent.core.task.request_service import decide_request

    decided = None
    try:
        decided = await decide_request(db, req.confirm_id, user.id, "approve" if req.approved else "reject")
    except LookupError:
        pass  # no persistent row (legacy path); resolve the Future below

    await _resolve_persisted_confirmation(req.confirm_id, req.approved)
    if not (decided and decided.get("future_resolved")) and not future.done():
        future.set_result(req.approved)
    return {"status": "ok"}
