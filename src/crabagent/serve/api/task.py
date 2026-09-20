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
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                deadline_dt = datetime.datetime.strptime(req.deadline[:16], fmt)
                break
            except ValueError:
                continue

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
        workspace=req.workspace,
        goal_id=req.goal_id,
        owner_type=req.owner_type,
        owner_name=req.owner_name,
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
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                kwargs["deadline"] = datetime.datetime.strptime(req.deadline[:16], fmt)
                break
            except ValueError:
                continue

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


@router.post("/{task_id}/start")
async def start_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a task in_progress and create a linked AgentRun."""
    from crabagent.core.task import service as task_service

    try:
        task, run_id = await task_service.start_agent_run(
            db,
            task_id,
            user.id,
            agent_name="main",
            session_id="",
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task, "run_id": run_id}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a task and finalize its active run as cancelled."""
    from crabagent.core.task import service as task_service

    task = await task_service.cancel_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/mark-result-viewed")
async def mark_result_viewed(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record when the user actually opened the task result."""
    from crabagent.core.task import service as task_service

    task = await task_service.mark_result_viewed(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/runs")
async def list_task_runs(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all runs belonging to a task, newest first."""
    from crabagent.core.task import service as task_service

    return await task_service.list_task_runs(db, task_id, user.id)


class RollbackRequest(BaseModel):
    force: bool = False


@router.get("/{task_id}/runs/{run_id}/changes")
async def get_run_changes(
    task_id: int,
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """File-level changes protected by this run's recovery points."""
    from crabagent.core.task.run_recovery import list_run_changes

    try:
        return await list_run_changes(db, task_id, run_id, user.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/{task_id}/runs/{run_id}/rollback")
async def rollback_run(
    task_id: int,
    run_id: int,
    req: RollbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Undo one run by restoring its pre-run snapshots.

    Refuses (409) when files were modified after this run unless forced.
    """
    from crabagent.core.task.run_recovery import rollback_run as _rollback

    try:
        result = await _rollback(db, task_id, run_id, user.id, force=req.force)
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")
    if result["status"] == "conflict":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed/partial/cancelled task with a fresh run (history kept)."""
    from crabagent.core.task.run_recovery import retry_task as _retry

    try:
        task, run_id = await _retry(db, task_id, user.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"task": task, "run_id": run_id}


@router.get("/{task_id}/detail")
async def get_task_detail(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-shot payload for the task detail drawer."""
    from crabagent.core.task import service as task_service
    from crabagent.core.task.artifact_service import list_artifacts
    from crabagent.core.task.store import get_task as _get

    task = await _get(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    runs = await task_service.list_task_runs(db, task_id, user.id)
    active_run = next((r for r in runs if r["id"] == task.get("active_run_id")), None)
    artifacts = await list_artifacts(db, task_id, user.id)
    events = await task_service.list_task_events(db, task_id, user.id)
    return {
        "task": task,
        "active_run": active_run,
        "runs": runs,
        "artifacts": artifacts,
        "recent_events": events,
    }


@router.get("/{task_id}/artifacts")
async def list_task_artifacts(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.task.artifact_service import list_artifacts
    from crabagent.core.task.store import get_task as _get

    task = await _get(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return await list_artifacts(db, task_id, user.id)


@router.get("/{task_id}/checks")
async def list_task_checks(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from crabagent.core.database import TaskCheck
    from crabagent.core.task.store import get_task as _get

    task = await _get(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = await db.execute(
        select(TaskCheck).where(TaskCheck.task_id == task_id, TaskCheck.user_id == user.id).order_by(TaskCheck.position)
    )
    return [
        {
            "id": c.id,
            "task_id": c.task_id,
            "run_id": c.run_id,
            "title": c.title,
            "required": c.required,
            "status": c.status,
            "evidence": c.evidence,
            "verified_at": c.verified_at.isoformat() if c.verified_at else None,
        }
        for c in result.scalars().all()
    ]
