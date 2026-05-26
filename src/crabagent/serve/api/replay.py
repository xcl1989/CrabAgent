from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from crabagent.core.database import Message, async_session_factory
from crabagent.core.event import AgentEvent, EventType

router = APIRouter(tags=["replay"])


@router.get("/sessions/{session_id}/replay")
async def replay_branch(
    session_id: str,
    request: Request,
    token: str = Query(..., description="JWT token"),
    branch: str = Query("main"),
    speed: float = Query(1.0, ge=0.1, le=10.0),
):
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id
    from crabagent.serve.services.conversation import get_conversation

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    async with async_session_factory() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.enabled:
            raise HTTPException(status_code=401, detail="User not found or disabled")
        conv = await get_conversation(db, session_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=403, detail="Not your session")

        stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id, Message.branch_id == branch)
            .order_by(Message.sequence.asc(), Message.id.asc())
        )
        result = await db.execute(stmt)
        msgs = list(result.scalars().all())

    if not msgs:
        raise HTTPException(status_code=404, detail=f"No messages in branch '{branch}'")

    delay = 0.5 / speed

    async def generate():
        start_event = AgentEvent(
            type=EventType.AGENT_START,
            data={"replay": True, "total": len(msgs), "branch_id": branch},
        )
        yield start_event.to_sse()

        for i, msg in enumerate(msgs):
            if await request.is_disconnected():
                break

            progress = AgentEvent(
                type=EventType.ITERATION_START,
                data={"replay_progress": i + 1, "replay_total": len(msgs)},
            )
            yield progress.to_sse()

            if msg.role == "user":
                yield AgentEvent(type=EventType.TEXT_DELTA, data={"text": msg.content or "", "role": "user"}).to_sse()
                yield AgentEvent(type=EventType.TEXT_DONE, data={"text": msg.content or "", "role": "user"}).to_sse()

            elif msg.role == "assistant":
                if msg.reasoning_content:
                    yield AgentEvent(type=EventType.THINKING_DELTA, data={"text": msg.reasoning_content}).to_sse()
                    yield AgentEvent(type=EventType.THINKING_DONE, data={"text": msg.reasoning_content}).to_sse()

                if msg.tool_calls:
                    try:
                        tool_calls = json.loads(msg.tool_calls)
                    except (json.JSONDecodeError, TypeError):
                        tool_calls = []
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        yield AgentEvent(
                            type=EventType.TOOL_CALL,
                            data={
                                "name": fn.get("name", "unknown"),
                                "arguments": fn.get("arguments", {}),
                                "id": tc.get("id", ""),
                            },
                        ).to_sse()
                        await asyncio.sleep(delay)

                if msg.content:
                    yield AgentEvent(
                        type=EventType.TEXT_DELTA, data={"text": msg.content, "role": "assistant"}
                    ).to_sse()
                    yield AgentEvent(type=EventType.TEXT_DONE, data={"text": msg.content, "role": "assistant"}).to_sse()

            elif msg.role == "tool":
                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={"name": msg.name or "tool", "result": msg.content or ""},
                ).to_sse()

            await asyncio.sleep(delay)

        yield AgentEvent(
            type=EventType.AGENT_END,
            data={"replay": True, "branch_id": branch, "total": len(msgs)},
        ).to_sse()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
