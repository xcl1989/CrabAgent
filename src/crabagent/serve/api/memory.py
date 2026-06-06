"""Memory management API — list, search, update, create, delete."""

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import (
    AgentMemory,
    Conversation,
    User,
    agent_memory_delete,
    agent_memory_upsert,
    get_db,
)
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])


class CreateMemoryRequest(BaseModel):
    memory_type: str
    agent_name: str
    category: str
    key: str
    content: str
    importance: float = 0.5


@router.get("")
async def list_memories(
    memory_type: str = Query("", description="Filter by memory type"),
    category: str = Query("", description="Filter by category"),
    agent_name: str = Query("", description="Filter by agent name"),
    workspace: str = Query("", description="Filter by workspace path"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    q: str = Query("", description="Search in content"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all memories with optional filters. Returns full content."""
    query = select(AgentMemory).where(AgentMemory.user_id == user.id)

    if workspace:
        # Workspace-scoped: join through Conversation.source_session
        query = (
            select(AgentMemory)
            .join(Conversation, AgentMemory.source_session == Conversation.session_id)
            .where(
                AgentMemory.user_id == user.id,
                Conversation.workspace == workspace,
                AgentMemory.source_session != "",
            )
        )

    if memory_type:
        query = query.where(AgentMemory.memory_type == memory_type)
    if category:
        query = query.where(AgentMemory.category == category)
    if agent_name:
        query = query.where(AgentMemory.agent_name == agent_name)

    query = query.order_by(AgentMemory.updated_at.desc()).limit(limit)

    result = await db.execute(query)
    items = [
        {
            "id": r.id,
            "memory_type": r.memory_type,
            "agent_name": r.agent_name,
            "category": r.category,
            "key": r.key,
            "content": r.content,
            "importance": r.importance,
            "confidence": r.confidence,
            "access_count": r.access_count,
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in result.scalars().all()
    ]

    if q:
        q_lower = q.lower()
        items = [i for i in items if q_lower in i.get("content", "").lower()]

    return items


@router.get("/{key:path}")
async def get_memory(
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single memory by key."""
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.user_id == user.id,
            AgentMemory.key == key,
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "id": m.id,
        "memory_type": m.memory_type,
        "agent_name": m.agent_name,
        "category": m.category,
        "key": m.key,
        "content": m.content,
        "importance": m.importance,
        "confidence": m.confidence,
        "access_count": m.access_count,
        "updated_at": m.updated_at.isoformat() if m.updated_at else "",
    }


@router.post("")
async def create_memory(
    req: CreateMemoryRequest,
    user: User = Depends(get_current_user),
):
    """Create a new memory entry."""
    await agent_memory_upsert(
        user_id=user.id,
        memory_type=req.memory_type,
        agent_name=req.agent_name,
        category=req.category,
        key=req.key,
        content=req.content,
        importance=req.importance,
        confidence=1.0,
        source="user",
    )
    return {"status": "created", "key": req.key}


@router.patch("/{key:path}")
async def update_memory(
    key: str,
    content: str = Query("", description="New content"),
    importance: float = Query(None, ge=0.0, le=1.0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a memory entry's content and/or importance."""
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.user_id == user.id,
            AgentMemory.key == key,
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")

    if content:
        m.content = content
    if importance is not None:
        m.importance = importance
    m.updated_at = __import__("datetime").datetime.utcnow()
    await db.commit()

    return {"status": "updated", "key": key}


@router.delete("/{key:path}")
async def delete_memory(
    key: str,
    user: User = Depends(get_current_user),
):
    """Delete a memory entry."""
    deleted = await agent_memory_delete(user.id, key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "key": key}
