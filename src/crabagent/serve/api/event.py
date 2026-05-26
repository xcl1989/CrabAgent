from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from crabagent.core.event import AgentEvent, EventType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


async def _verify_sse_token(token: str, session_id: str):
    from crabagent.core.database import async_session_factory
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id
    from crabagent.serve.services.conversation import get_conversation

    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return None

    async with async_session_factory() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.enabled:
            return None
        conv = await get_conversation(db, session_id)
        if not conv or conv.user_id != user_id:
            return None
    return user


@router.get("/events")
async def event_stream(
    request: Request,
    session_id: str = Query(..., description="Session ID to subscribe to"),
    token: str = Query(..., description="JWT token for authentication"),
):
    user = await _verify_sse_token(token, session_id)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid token or unauthorized")

    queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=50)
    queue_id = uuid.uuid4().hex

    if not hasattr(request.app.state, "event_queues"):
        request.app.state.event_queues = {}
    request.app.state.event_queues[queue_id] = (session_id, queue, time.time())

    connected_event = AgentEvent(
        type=EventType.MESSAGE_CREATED,
        data={"connected": True, "session_id": session_id, "queue_id": queue_id},
    )

    async def generate():
        yield connected_event.to_sse()

        from crabagent.core.agent.agents import get_running_subs

        for sub_id, sub in get_running_subs(session_id).items():
            yield AgentEvent(
                type=EventType.SUB_AGENT_START,
                data={
                    "sub_agent_id": sub_id,
                    "agent_name": sub["agent_name"],
                    "display_name": sub["display_name"],
                    "task": sub["task"],
                },
            ).to_sse()

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if isinstance(event, AgentEvent):
                        try:
                            yield event.to_sse()
                        except (TypeError, ValueError) as exc:
                            logger.error(
                                "SSE serialize error session=%s event=%s: %s",
                                session_id[:8],
                                event.type,
                                exc,
                            )
                    elif isinstance(event, dict):
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            queues = getattr(request.app.state, "event_queues", {})
            queues.pop(queue_id, None)
            logger.info(
                "SSE disconnected session=%s queue=%s remaining_queues=%d",
                session_id[:8],
                queue_id[:8],
                len(queues),
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _verify_global_token(token: str):
    from crabagent.core.database import async_session_factory
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id

    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return None

    async with async_session_factory() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.enabled:
            return None
    return user


@router.get("/events/global")
async def global_event_stream(
    request: Request,
    token: str = Query(..., description="JWT token for authentication"),
):
    user = await _verify_global_token(token)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid token or unauthorized")

    queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=500)
    queue_id = uuid.uuid4().hex

    if not hasattr(request.app.state, "global_event_queues"):
        request.app.state.global_event_queues = {}
    request.app.state.global_event_queues[queue_id] = (queue, time.time())

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            queues = getattr(request.app.state, "global_event_queues", {})
            queues.pop(queue_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
