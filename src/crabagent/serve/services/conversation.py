from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Conversation


async def create_conversation(
    db: AsyncSession,
    user_id: int,
    workspace: str = "",
    model: str = "",
    title: str = "",
) -> Conversation:
    session_id = uuid.uuid4().hex[:16]
    conv = Conversation(
        session_id=session_id,
        user_id=user_id,
        title=title,
        workspace=workspace,
        model=model,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(db: AsyncSession, session_id: str) -> Conversation | None:
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    return result.scalar_one_or_none()


async def list_conversations(db: AsyncSession, user_id: int) -> list[Conversation]:
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def update_conversation(db: AsyncSession, session_id: str, **kwargs) -> Conversation | None:
    conv = await get_conversation(db, session_id)
    if not conv:
        return None
    for key, value in kwargs.items():
        if hasattr(conv, key):
            setattr(conv, key, value)
    await db.commit()
    await db.refresh(conv)
    return conv


async def delete_conversation(db: AsyncSession, session_id: str) -> bool:
    from crabagent.core.database import Message

    conv = await get_conversation(db, session_id)
    if not conv:
        return False
    await db.execute(delete(Message).where(Message.conversation_id == conv.id))
    await db.execute(delete(Conversation).where(Conversation.session_id == session_id))
    await db.commit()
    return True
