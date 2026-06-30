from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.core.event import AgentEvent, EventBus, EventType
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}", tags=["input"])

# input_id → (future, question, options, session_id)
_pending_inputs: dict[str, tuple[asyncio.Future[str], str, list[str] | None, str]] = {}


async def request_user_input(
    event_bus: EventBus,
    session_id: str,
    question: str,
    options: list[str] | None = None,
) -> asyncio.Future[str]:
    input_id = uuid.uuid4().hex[:12]
    future: asyncio.Future[str] = asyncio.Future()
    _pending_inputs[input_id] = (future, question, options, session_id)
    data: dict = {
        "input_id": input_id,
        "question": question,
        "session_id": session_id,
    }
    if options:
        data["options"] = options
    await event_bus.emit(
        AgentEvent(
            type=EventType.USER_INPUT_REQUEST,
            data=data,
        )
    )
    return future


def pop_pending(input_id: str) -> asyncio.Future[str] | None:
    entry = _pending_inputs.pop(input_id, None)
    return entry[0] if entry else None


def get_pending_for_session(session_id: str) -> list[dict]:
    """Return all pending (unanswered) user_input requests for a session.

    Used by the SSE endpoint to re-emit pending requests on reconnect,
    so that page refresh doesn't lose the input UI.
    """
    result = []
    for input_id, (future, question, options, sid) in _pending_inputs.items():
        if sid != session_id or future.done():
            continue
        item: dict = {
            "input_id": input_id,
            "question": question,
            "session_id": sid,
        }
        if options:
            item["options"] = options
        result.append(item)
    return result


class UserInputRequest(BaseModel):
    input_id: str
    answer: str


@router.post("/user-input")
async def submit_user_input(
    session_id: str,
    req: UserInputRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    future = pop_pending(req.input_id)
    if not future or future.done():
        raise HTTPException(status_code=404, detail="Input request not found or expired")
    future.set_result(req.answer)
    return {"status": "ok"}
