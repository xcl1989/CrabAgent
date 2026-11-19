from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import ConversationMemoryAnchor, ConversationMemoryInjection, Message, User, get_db
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

    stmt = select(Message.branch_id).where(Message.conversation_id == conv.id).distinct()
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
        branches.append(
            BranchInfo(
                branch_id=bid,
                name=bid,
                message_count=len(msgs),
                parent_message_id=parent_msg_id,
            )
        )

    return branches


@router.post("")
async def create_branch(
    session_id: str,
    req: BranchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Keep the source history, snapshot copy and active-branch update in one write transaction.
    if db.bind.dialect.name == "sqlite":
        await db.execute(text("BEGIN IMMEDIATE"))
    conv = await get_owned_conversation(db, session_id, user)
    source_branch = conv.active_branch or "main"

    target = await db.get(Message, req.message_id)
    if not target or target.conversation_id != conv.id or target.branch_id != source_branch:
        raise HTTPException(status_code=404, detail="Message not found in the active branch")

    new_branch = req.name or f"branch-{uuid.uuid4().hex[:8]}"
    existing_branch = await db.scalar(select(Message.id).where(
        Message.conversation_id == conv.id, Message.branch_id == new_branch,
    ).limit(1))
    if existing_branch is not None:
        raise HTTPException(status_code=409, detail="Branch already exists")

    earlier = Message.sequence < target.sequence
    if target.role != "user":
        earlier = earlier | ((Message.sequence == target.sequence) & (Message.id <= target.id))
    source_msgs = (await db.scalars(select(Message).where(
        Message.conversation_id == conv.id, Message.branch_id == source_branch, earlier,
    ).order_by(Message.sequence, Message.id))).all()

    max_seq_result = await db.execute(
        select(Message.sequence).where(Message.conversation_id == conv.id).order_by(Message.sequence.desc()).limit(1)
    )
    max_seq_row = max_seq_result.first()
    next_seq = (max_seq_row[0] + 1) if max_seq_row else 1

    copied_users = {}
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
            agent=msg.agent,
            compressed=msg.compressed,
        )
        db.add(new_msg)
        if msg.role == "user":
            copied_users[msg.id] = new_msg
        next_seq += 1

    await db.flush()
    await _copy_memory_batches(db, conv.id, source_branch, new_branch, copied_users)
    conv.active_branch = new_branch
    await db.commit()

    return {
        "branch_id": new_branch,
        "source_message_id": req.message_id,
        "copied_messages": len(source_msgs),
    }


async def _copy_memory_batches(db, conversation_id, source_branch, new_branch, copied_users):
    anchor_ids = list(copied_users)
    for offset in range(0, len(anchor_ids), 500):
        chunk = anchor_ids[offset:offset + 500]
        anchor = ConversationMemoryAnchor
        batches = (await db.scalars(select(anchor).where(
            anchor.conversation_id == conversation_id, anchor.branch_id == source_branch,
            anchor.anchor_message_id.in_(chunk),
        ))).all()
        for batch in batches:
            db.add(anchor(
                conversation_id=conversation_id, branch_id=new_branch,
                anchor_message_id=copied_users[batch.anchor_message_id].id,
                # Unsent prepared batches close empty in a fork; they cannot be replayed.
                first_admission_recorded=True,
            ))
        admitted_ids = [batch.anchor_message_id for batch in batches if batch.first_admission_recorded]
        if not admitted_ids:
            continue
        snapshot = ConversationMemoryInjection
        rows = (await db.scalars(select(snapshot).where(
            snapshot.conversation_id == conversation_id, snapshot.branch_id == source_branch,
            snapshot.anchor_message_id.in_(admitted_ids), snapshot.admitted.is_(True),
        ))).all()
        for row in rows:
            db.add(snapshot(
                conversation_id=conversation_id, branch_id=new_branch,
                anchor_message_id=copied_users[row.anchor_message_id].id,
                memory_uid=row.memory_uid, content_revision=row.content_revision,
                visibility_epoch=row.visibility_epoch, ordinal=row.ordinal, render_version=row.render_version,
                snapshot_payload=row.snapshot_payload, supersedes_revision=row.supersedes_revision,
                token_count_estimate=row.token_count_estimate, created_at=row.created_at, admitted=True,
            ))


@router.post("/switch")
async def switch_branch(
    session_id: str,
    req: SwitchBranchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)

    stmt = select(Message.id).where(Message.conversation_id == conv.id, Message.branch_id == req.branch_id).limit(1)
    result = await db.execute(stmt)
    if not result.first():
        raise HTTPException(status_code=404, detail=f"Branch '{req.branch_id}' not found")

    await conv_svc.update_conversation(db, session_id, active_branch=req.branch_id)

    return {"branch_id": req.branch_id, "session_id": session_id}
