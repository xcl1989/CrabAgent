from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    assignee: str = ""
    deadline: str | None = None
    source: str = "manual"
    source_ref: str = ""
    project: str = ""
    priority: str = "medium"


class UpdateTaskRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    assignee: str | None = None
    deadline: str | None = None
    status: str | None = None
    priority: str | None = None
    project: str | None = None


@router.get("")
async def list_tasks(
    status: str = "all",
    project: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.store import list_tasks as _list

    return await _list(db, user.id, status, project)


@router.post("")
async def create_task(
    req: CreateTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.store import add_task as _add

    deadline_dt = None
    if req.deadline:
        try:
            deadline_dt = datetime.datetime.strptime(req.deadline[:10], "%Y-%m-%d")
        except ValueError:
            pass

    return await _add(
        db,
        user_id=user.id,
        title=req.title,
        description=req.description,
        assignee=req.assignee,
        deadline=deadline_dt,
        source=req.source,
        source_ref=req.source_ref,
        project=req.project,
        priority=req.priority,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.store import get_task as _get

    t = await _get(db, task_id, user.id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return t


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    req: UpdateTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.store import update_task as _update

    kwargs = {}
    for field in ("title", "description", "assignee", "status", "priority", "project"):
        val = getattr(req, field, None)
        if val is not None:
            kwargs[field] = val
    if req.deadline is not None:
        try:
            kwargs["deadline"] = datetime.datetime.strptime(
                req.deadline[:10], "%Y-%m-%d"
            )
        except ValueError:
            pass

    t = await _update(db, task_id, user.id, **kwargs)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return t


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.store import delete_task as _delete

    ok = await _delete(db, task_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok"}
