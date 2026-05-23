from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import ScheduledTask, User, get_db
from crabagent.serve.deps import get_current_user
from crabagent.serve.scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


class ScheduledTaskResponse(BaseModel):
    id: int
    name: str
    prompt: str
    cron_expression: str
    model: str
    enabled: bool
    next_run_at: str | None
    last_run_at: str | None
    last_status: str
    last_error: str
    last_conversation_id: str
    created_at: str


class CreateScheduledTaskRequest(BaseModel):
    name: str
    prompt: str
    cron_expression: str
    model: str = ""


class UpdateScheduledTaskRequest(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cron_expression: str | None = None
    model: str | None = None
    enabled: bool | None = None


def _to_response(t: ScheduledTask) -> ScheduledTaskResponse:
    return ScheduledTaskResponse(
        id=t.id,
        name=t.name,
        prompt=t.prompt,
        cron_expression=t.cron_expression,
        model=t.model or "",
        enabled=t.enabled,
        next_run_at=t.next_run_at.isoformat() if t.next_run_at else None,
        last_run_at=t.last_run_at.isoformat() if t.last_run_at else None,
        last_status=t.last_status or "",
        last_error=t.last_error or "",
        last_conversation_id=t.last_conversation_id or "",
        created_at=t.created_at.isoformat() if t.created_at else "",
    )


@router.get("", response_model=list[ScheduledTaskResponse])
async def list_tasks(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ScheduledTask).order_by(ScheduledTask.created_at.desc())
    )
    return [_to_response(r) for r in result.scalars().all()]


@router.post("", response_model=ScheduledTaskResponse)
async def create_task(
    req: CreateScheduledTaskRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    parts = req.cron_expression.strip().split()
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail="cron 表达式必须包含5个字段（分 时 日 月 周）")

    task = ScheduledTask(
        user_id=user.id,
        name=req.name,
        prompt=req.prompt,
        cron_expression=req.cron_expression.strip(),
        model=req.model or "",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    await get_scheduler().add_task(task)
    return _to_response(task)


@router.patch("/{task_id}", response_model=ScheduledTaskResponse)
async def update_task(
    task_id: int,
    req: UpdateScheduledTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    cron_changed = False
    if req.name is not None:
        task.name = req.name
    if req.prompt is not None:
        task.prompt = req.prompt
    if req.cron_expression is not None:
        parts = req.cron_expression.strip().split()
        if len(parts) != 5:
            raise HTTPException(status_code=400, detail="cron 表达式必须包含5个字段")
        task.cron_expression = req.cron_expression.strip()
        cron_changed = True
    if req.model is not None:
        task.model = req.model
    if req.enabled is not None:
        task.enabled = req.enabled

    await db.commit()
    await db.refresh(task)

    if cron_changed or req.enabled is not None:
        get_scheduler().remove_task(task_id)
        if task.enabled:
            await get_scheduler().add_task(task)

    await db.refresh(task)
    if cron_changed and task.enabled:
        try:
            from datetime import datetime

            from apscheduler.triggers.cron import CronTrigger

            parts = task.cron_expression.strip().split()
            tz = datetime.now().astimezone().tzinfo
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4], timezone=tz,
            )
            next_time = trigger.get_next_fire_time(None, datetime.now(tz=tz))
            if next_time:
                task.next_run_at = next_time.replace(tzinfo=None)
                await db.commit()
        except Exception:
            pass
    await db.refresh(task)
    return _to_response(task)


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete

    result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    get_scheduler().remove_task(task_id)
    await db.execute(delete(ScheduledTask).where(ScheduledTask.id == task_id))
    await db.commit()
    return {"status": "deleted", "id": task_id}


@router.post("/{task_id}/run")
async def run_task_now(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ScheduledTask).where(ScheduledTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    import asyncio

    s = get_scheduler()
    asyncio.create_task(s._execute(task_id))
    return {"status": "running", "id": task_id}
