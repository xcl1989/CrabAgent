from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import BrowserTask, BrowserTaskEvent, User, get_db
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}/browser-tasks", tags=["browser-tasks"])


class CreateBrowserTaskRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    url: str = ""


class UpdateBrowserTaskRequest(BaseModel):
    status: str | None = None
    url: str | None = None
    page_version: int | None = None
    summary: str | None = Field(default=None, max_length=4000)


class CreateBrowserTaskEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    detail: str = Field(default="", max_length=2000)
    risk: str = Field(default="low", max_length=20)
    data: dict = Field(default_factory=dict)


def _task_dict(task: BrowserTask) -> dict:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "goal": task.goal,
        "status": task.status,
        "url": task.url,
        "page_version": task.page_version,
        "summary": task.summary,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _event_dict(event: BrowserTaskEvent) -> dict:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "detail": event.detail,
        "risk": event.risk,
        "data": event.data or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def _owned_task(db: AsyncSession, session_id: str, task_id: int, user: User) -> BrowserTask:
    task = await db.get(BrowserTask, task_id)
    if not task or task.session_id != session_id or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Browser task not found")
    return task


@router.get("")
async def list_browser_tasks(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    result = await db.execute(
        select(BrowserTask).where(BrowserTask.session_id == session_id).order_by(BrowserTask.updated_at.desc())
    )
    return {"tasks": [_task_dict(task) for task in result.scalars()]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_browser_task(
    session_id: str,
    req: CreateBrowserTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    task = BrowserTask(session_id=session_id, user_id=user.id, goal=req.goal, url=req.url, status="running")
    db.add(task)
    await db.flush()
    db.add(BrowserTaskEvent(task_id=task.id, event_type="created", detail="Browser task started"))
    await db.commit()
    await db.refresh(task)
    return _task_dict(task)


@router.patch("/{task_id}")
async def update_browser_task(
    session_id: str,
    task_id: int,
    req: UpdateBrowserTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _owned_task(db, session_id, task_id, user)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    if task.status in {"completed", "failed", "cancelled"} and task.completed_at is None:
        task.completed_at = datetime.now()
    await db.commit()
    await db.refresh(task)
    return _task_dict(task)


@router.get("/{task_id}/events")
async def list_browser_task_events(
    session_id: str,
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_task(db, session_id, task_id, user)
    result = await db.execute(
        select(BrowserTaskEvent).where(BrowserTaskEvent.task_id == task_id).order_by(BrowserTaskEvent.created_at.asc())
    )
    return {"events": [_event_dict(event) for event in result.scalars()]}


@router.post("/{task_id}/events", status_code=status.HTTP_201_CREATED)
async def create_browser_task_event(
    session_id: str,
    task_id: int,
    req: CreateBrowserTaskEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_task(db, session_id, task_id, user)
    event = BrowserTaskEvent(task_id=task_id, **req.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return _event_dict(event)
