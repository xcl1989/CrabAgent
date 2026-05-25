from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Message, User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services import conversation as conv_svc

router = APIRouter(prefix="/sessions/{session_id}/branches", tags=["branches"])


class BranchRequest(BaseModel):
    message_id: int
    name: str | None = None


class BranchInfo(BaseModel):
    branch_id: str
    name: str
    message_count: int
    parent_message_id: int


class SwitchBranchRequest(BaseModel):
    branch_id: str


@router.get("", response_model=list[BranchInfo])
async def list_branches(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)

    stmt = (
        select(Message.branch_id)
        .where(Message.conversation_id == conv.id)
        .distinct()
    )
    result = await db.execute(stmt)
    branch_ids = [row[0] for row in result.fetchall()]

    branches = []
    for bid in branch_ids:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id, Message.branch_id == bid)
            .order_by(Message.sequence.asc())
        )
        result = await db.execute(stmt)
        msgs = list(result.scalars().all())
        if not msgs:
            continue
        parent_msg_id = msgs[0].parent_id or msgs[0].id
        branches.append(BranchInfo(
            branch_id=bid,
            name=bid,
            message_count=len(msgs),
            parent_message_id=parent_msg_id,
        ))

    return branches


@router.post("")
async def create_branch(
    session_id: str,
    req: BranchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)

    target = await db.get(Message, req.message_id)
    if not target or target.conversation_id != conv.id:
        raise HTTPException(status_code=404, detail="Message not found in this session")

    new_branch = req.name or f"branch-{uuid.uuid4().hex[:8]}"

    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.branch_id == conv.active_branch,
            Message.sequence <= target.sequence,
        )
        .order_by(Message.sequence.asc(), Message.id.asc())
    )
    result = await db.execute(stmt)
    source_msgs = list(result.scalars().all())

    if target.role == "user":
        source_msgs = [m for m in source_msgs if m.sequence < target.sequence]

    max_seq_result = await db.execute(
        select(Message.sequence)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    max_seq_row = max_seq_result.first()
    next_seq = (max_seq_row[0] + 1) if max_seq_row else 1

    for msg in source_msgs:
        new_msg = Message(
            conversation_id=conv.id,
            sequence=next_seq,
            role=msg.role,
            content=msg.content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
            reasoning_content=msg.reasoning_content,
            branch_id=new_branch,
            parent_id=msg.parent_id,
        )
        db.add(new_msg)
        next_seq += 1

    await db.commit()

    await conv_svc.update_conversation(db, session_id, active_branch=new_branch)

    return {
        "branch_id": new_branch,
        "source_message_id": req.message_id,
        "copied_messages": len(source_msgs),
    }


@router.post("/switch")
async def switch_branch(
    session_id: str,
    req: SwitchBranchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)

    stmt = (
        select(Message.id)
        .where(Message.conversation_id == conv.id, Message.branch_id == req.branch_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    if not result.first():
        raise HTTPException(status_code=404, detail=f"Branch '{req.branch_id}' not found")

    await conv_svc.update_conversation(db, session_id, active_branch=req.branch_id)

    return {"branch_id": req.branch_id, "session_id": session_id}
