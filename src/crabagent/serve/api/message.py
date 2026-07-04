from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Message, User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services.message import (
    _strip_base64_images,
    _try_inline_image,
    get_messages,
    message_to_response,
)

router = APIRouter(tags=["messages"])


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    branch: str | None = Query(None),
    include_compressed: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)
    branch_id = branch or conv.active_branch or "main"
    msgs = await get_messages(
        db, conv.id, limit=limit, offset=offset, branch_id=branch_id,
        include_compressed=include_compressed,
    )
    # Filter out internal messages from frontend display
    msgs = [m for m in msgs if m.role not in ("agent_switch", "experience")]
    # Strip base64 image data for fast list loading; frontend fetches images
    # lazily via /messages/{message_id}/images
    return [message_to_response(m, strip_images=True) for m in msgs]


@router.get("/sessions/{session_id}/messages/{message_id}/images")
async def get_message_images(
    session_id: str,
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return base64 image data for a single message (lazy-loaded by frontend)."""
    conv = await get_owned_conversation(db, session_id, user)

    stmt = select(Message).where(
        Message.id == message_id,
        Message.conversation_id == conv.id,
    )
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    images: list[str] = []

    if msg.content:
        _, extracted = _strip_base64_images(msg.content)
        images.extend(extracted)

    # Screenshot role: content is a file path
    if msg.role == "screenshot" and msg.content:
        data_url = _try_inline_image(msg.content)
        if data_url:
            images.append(data_url)

    return {"images": images}
