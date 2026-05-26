from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Todo


async def add_todo(db: AsyncSession, session_id: str, task: str) -> dict:
    todo = Todo(session_id=session_id, task=task)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return _todo_to_dict(todo)


async def list_todos(db: AsyncSession, session_id: str, filter_: str = "all") -> list[dict]:
    stmt = select(Todo).where(Todo.session_id == session_id).order_by(Todo.created_at.desc())
    if filter_ == "pending":
        stmt = stmt.where(not Todo.done)
    elif filter_ == "done":
        stmt = stmt.where(Todo.done)
    result = await db.execute(stmt)
    return [_todo_to_dict(t) for t in result.scalars().all()]


async def mark_done(db: AsyncSession, todo_id: int, session_id: str) -> bool:
    result = await db.execute(select(Todo).where(Todo.id == todo_id, Todo.session_id == session_id))
    t = result.scalar_one_or_none()
    if not t:
        return False
    t.done = True
    await db.commit()
    return True


async def delete_todo(db: AsyncSession, todo_id: int, session_id: str) -> bool:
    result = await db.execute(select(Todo).where(Todo.id == todo_id, Todo.session_id == session_id))
    t = result.scalar_one_or_none()
    if not t:
        return False
    await db.delete(t)
    await db.commit()
    return True


def _todo_to_dict(t: Todo) -> dict:
    return {
        "id": t.id,
        "task": t.task,
        "done": t.done,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
