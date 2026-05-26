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

_pending_inputs: dict[str, asyncio.Future[str]] = {}


def request_user_input(
    event_bus: EventBus,
    session_id: str,
    question: str,
    options: list[str] | None = None,
) -> asyncio.Future[str]:
    input_id = uuid.uuid4().hex[:12]
    future: asyncio.Future[str] = asyncio.Future()
    _pending_inputs[input_id] = future
    data: dict = {
        "input_id": input_id,
        "question": question,
        "session_id": session_id,
    }
    if options:
        data["options"] = options
    event_bus.emit_sync(
        AgentEvent(
            type=EventType.USER_INPUT_REQUEST,
            data=data,
        )
    )
    return future


def pop_pending(input_id: str) -> asyncio.Future[str] | None:
    return _pending_inputs.pop(input_id, None)


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
