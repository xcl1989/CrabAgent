"""Memory management API — list, search, update, create, delete."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import AgentMemory, MemoryEmbedding, User, agent_memory_upsert, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])


class CreateMemoryRequest(BaseModel):
    memory_type: str
    agent_name: str
    category: str
    key: str
    content: str
    importance: float = 0.5
    scope: str = ""
    workspace_path: str = ""
    recall_policy: str = ""


def _memory_to_dict(m: AgentMemory) -> dict:
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
        "scope": getattr(m, "scope", "") or "",
        "workspace_path": getattr(m, "workspace_path", "") or "",
        "recall_policy": getattr(m, "recall_policy", "") or "",
        "updated_at": m.updated_at.isoformat() if m.updated_at else "",
    }


@router.get("")
async def list_memories(
    memory_type: str = Query("", description="Filter by memory type"),
    category: str = Query("", description="Filter by category"),
    agent_name: str = Query("", description="Filter by agent name"),
    workspace: str = Query("", description="Filter by workspace path"),
    scope: str = Query("", description="Filter by scope"),
    recall_policy: str = Query("", description="Filter by recall policy"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    q: str = Query("", description="Search in content"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all memories with optional filters. Returns full content."""
    query = select(AgentMemory).where(AgentMemory.user_id == user.id)

    if memory_type:
        query = query.where(AgentMemory.memory_type == memory_type)
    if category:
        query = query.where(AgentMemory.category == category)
    if agent_name:
        query = query.where(AgentMemory.agent_name == agent_name)
    if workspace:
        query = query.where(AgentMemory.workspace_path == workspace)
    if scope:
        query = query.where(AgentMemory.scope == scope)
    if recall_policy:
        query = query.where(AgentMemory.recall_policy == recall_policy)

    if q:
        query = query.where(or_(
            AgentMemory.content.icontains(q, autoescape=True),
            AgentMemory.key.icontains(q, autoescape=True),
        ))
    query = query.order_by(AgentMemory.updated_at.desc()).limit(limit)

    result = await db.execute(query)
    items = [_memory_to_dict(r) for r in result.scalars().all()]

    return items


@router.post("/semantic-consolidate")
async def semantic_consolidate_memories(user: User = Depends(get_current_user)):
    from crabagent.core.memory_batch_merge import semantic_consolidate

    return await semantic_consolidate(user.id)


@router.get("/archives/list")
async def memory_archives(user: User = Depends(get_current_user)):
    from crabagent.core.memory_compaction import list_archives

    return list_archives(user.id)


@router.get("/archives/{name}/entries")
async def memory_archive_entries(name: str, user: User = Depends(get_current_user)):
    from crabagent.core.memory_compaction import read_archive

    try:
        data = read_archive(user.id, name)
        return [{"id": row["id"], "key": row["key"], "content": row["content"]}
                for row in data["memories"] if row.get("user_id") == user.id]
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Archive not found") from None


@router.post("/archives/{name}/restore/{memory_id}")
async def memory_archive_restore(name: str, memory_id: int, user: User = Depends(get_current_user)):
    from crabagent.core.memory_compaction import restore_archived_memory

    try:
        return {"status": await restore_archived_memory(user.id, name, memory_id)}
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Archive or memory not found") from None


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
    rows = result.scalars().all()
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous memory key")
    m = rows[0] if rows else None
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _memory_to_dict(m)


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
        scope=req.scope,
        workspace_path=req.workspace_path,
        recall_policy=req.recall_policy,
    )
    return {"status": "created", "key": req.key}


@router.patch("/{key:path}")
async def update_memory(
    key: str,
    content: str = Query("", description="New content"),
    memory_id: int | None = Query(None),
    importance: float = Query(None, ge=0.0, le=1.0),
    scope: str = Query("", description="New scope"),
    workspace_path: str = Query("", description="New workspace path"),
    recall_policy: str = Query("", description="New recall policy"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a memory entry's fields."""
    stmt = select(AgentMemory).where(AgentMemory.user_id == user.id, AgentMemory.key == key)
    if memory_id is not None:
        stmt = stmt.where(AgentMemory.id == memory_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous memory key")
    m = rows[0] if rows else None
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")

    if content and content != m.content:
        await db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == m.id))
        m.content = content
    if importance is not None:
        m.importance = importance
    if scope:
        m.scope = scope
    if workspace_path:
        m.workspace_path = workspace_path
    if recall_policy:
        m.recall_policy = recall_policy
    m.updated_at = datetime.utcnow()
    await db.commit()

    return {"status": "updated", "key": key}


@router.delete("/{key:path}")
async def delete_memory(
    key: str,
    memory_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a memory entry."""
    stmt = select(AgentMemory).where(AgentMemory.user_id == user.id, AgentMemory.key == key)
    if memory_id is not None:
        stmt = stmt.where(AgentMemory.id == memory_id)
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous memory key")
    if not rows:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == rows[0].id))
    await db.delete(rows[0])
    await db.commit()
    return {"status": "deleted", "key": key}
