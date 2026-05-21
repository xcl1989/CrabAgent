from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}/todos", tags=["todos"])


class AddTodoRequest(BaseModel):
    task: str


@router.get("")
async def list_todos(
    session_id: str,
    filter: str = "all",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    from crabagent.core.todo.store import list_todos as _list

    return await _list(db, session_id, filter)


@router.post("")
async def add_todo(
    session_id: str,
    req: AddTodoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    from crabagent.core.todo.store import add_todo as _add

    return await _add(db, session_id, req.task)


@router.post("/{todo_id}/done")
async def mark_done(
    session_id: str,
    todo_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    from crabagent.core.todo.store import mark_done as _done

    ok = await _done(db, todo_id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"status": "ok"}


@router.delete("/{todo_id}")
async def delete_todo(
    session_id: str,
    todo_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    from crabagent.core.todo.store import delete_todo as _delete

    ok = await _delete(db, todo_id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"status": "ok"}
