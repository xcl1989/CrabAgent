from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services.message import get_messages, message_to_response

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
    return [message_to_response(m) for m in msgs]
