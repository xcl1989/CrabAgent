from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Message


async def save_message(
    db: AsyncSession,
    conversation_id: int,
    sequence: int,
    role: str,
    content: str = "",
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
    reasoning_content: str | None = None,
    branch_id: str = "main",
    parent_id: int | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        sequence=sequence,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        name=name,
        reasoning_content=reasoning_content,
        branch_id=branch_id,
        parent_id=parent_id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_messages(
    db: AsyncSession,
    conversation_id: int,
    limit: int | None = None,
    offset: int = 0,
    branch_id: str | None = None,
) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
    )
    if branch_id is not None:
        stmt = stmt.where(Message.branch_id == branch_id)
    stmt = stmt.order_by(Message.sequence.asc(), Message.id.asc())
    if offset:
        stmt = stmt.offset(offset)
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_messages(db: AsyncSession, conversation_id: int) -> int:
    from sqlalchemy import delete as sa_delete

    result = await db.execute(sa_delete(Message).where(Message.conversation_id == conversation_id))
    await db.commit()
    return result.rowcount


def message_to_dict(msg: Message) -> dict:
    d: dict = {"role": msg.role}

    if msg.content:
        if msg.content.startswith("["):
            try:
                d["content"] = json.loads(msg.content)
            except json.JSONDecodeError:
                d["content"] = msg.content
        else:
            d["content"] = msg.content
    else:
        d["content"] = None

    if msg.tool_calls:
        try:
            d["tool_calls"] = json.loads(msg.tool_calls)
        except json.JSONDecodeError:
            d["tool_calls"] = None

    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id

    if msg.name:
        d["name"] = msg.name

    if msg.reasoning_content:
        d["reasoning_content"] = msg.reasoning_content

    return d


def message_to_response(msg: Message) -> dict:
    d: dict = {
        "id": msg.id,
        "sequence": msg.sequence,
        "role": msg.role,
        "content": msg.content or "",
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
    if msg.tool_calls:
        try:
            d["tool_calls"] = json.loads(msg.tool_calls)
        except json.JSONDecodeError:
            d["tool_calls"] = None
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name:
        d["name"] = msg.name
    if msg.reasoning_content:
        d["reasoning_content"] = msg.reasoning_content
    d["branch_id"] = msg.branch_id or "main"
    d["parent_id"] = msg.parent_id
    return d
