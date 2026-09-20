from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.core.event import AgentEvent, EventBus, EventType
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}", tags=["input"])

logger = logging.getLogger(__name__)

INPUT_TTL_SECONDS = 300

# input_id → (future, question, options, session_id)
_pending_inputs: dict[str, tuple[asyncio.Future[str], str, list[str] | None, str]] = {}


async def request_user_input(
    event_bus: EventBus,
    session_id: str,
    question: str,
    options: list[str] | None = None,
    user_id: int = 1,
) -> asyncio.Future[str]:
    input_id = uuid.uuid4().hex[:12]
    future: asyncio.Future[str] = asyncio.Future()
    _pending_inputs[input_id] = (future, question, options, session_id)

    # Trusted work system: persist a TaskRequest so the question survives
    # restarts; the Future above is only a live bridge.
    try:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.request_service import create_request, register_live_future

        async with async_session_factory() as db:
            await create_request(
                db,
                user_id=user_id,
                request_type="choice" if options else "input",
                request_key=input_id,
                title=question[:200],
                session_id=session_id,
                question=question,
                options=options,
                risk_level="low",
                expires_at=datetime.datetime.now() + datetime.timedelta(seconds=INPUT_TTL_SECONDS + 10),
            )
        register_live_future(input_id, future)
    except Exception:
        logger.exception("Failed to persist TaskRequest for input %s", input_id)

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


@router.get("/pending-inputs")
async def list_pending_inputs(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    return {"inputs": get_pending_for_session(session_id)}


@router.post("/user-input")
async def submit_user_input(
    session_id: str,
    req: UserInputRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)

    future = pop_pending(req.input_id)

    # Persistent decision first: records the answer exactly once and
    # resolves any live bridge Future.
    from crabagent.core.task.request_service import decide_request

    decided = None
    try:
        decided = await decide_request(db, req.input_id, user.id, "answer", answer=req.answer)
    except LookupError:
        pass

    if not future or future.done():
        if decided is None:
            raise HTTPException(status_code=404, detail="Input request not found or expired")
        if decided["status"] == "expired":
            raise HTTPException(status_code=409, detail="Input request expired")
        return {"status": "ok", "future_resolved": decided.get("future_resolved", False)}

    if not (decided and decided.get("future_resolved")) and not future.done():
        future.set_result(req.answer)
    return {"status": "ok"}
