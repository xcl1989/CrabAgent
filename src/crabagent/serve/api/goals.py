from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import GoalCheckpoint, GoalEvent, User, get_db
from crabagent.core.event import AgentEvent, EventType
from crabagent.core.goals.service import (
    checkpoint_goal,
    create_goal,
    get_current_goal,
    goal_to_dict,
    update_goal,
)
from crabagent.serve.deps import get_current_user, get_owned_conversation

router = APIRouter(prefix="/sessions/{session_id}/goal", tags=["goals"])


async def _emit_goal_event(request: Request, session_id: str, event_type: EventType, goal: dict, **data) -> None:
    event = AgentEvent(type=event_type, data={"goal": goal, **data})
    for entry in list(getattr(request.app.state, "event_queues", {}).values()):
        if not isinstance(entry, tuple) or len(entry) < 3 or entry[0] != session_id:
            continue
        queue = entry[2]
        try:
            queue.put_nowait(event)
        except Exception:
            pass


class CreateGoalRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=4000)
    execution_model: str = Field(default="", max_length=200)
    execution_provider: str = Field(default="", max_length=100)
    execution_agent: str = Field(default="", max_length=100)
    reasoning_effort: str = Field(default="", max_length=50)
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    auto_continue: bool = False
    token_budget: int | None = Field(default=None, gt=0)
    max_auto_turns: int | None = Field(default=None, gt=0)


class UpdateGoalRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=4000)
    success_criteria: list[str] | None = None
    constraints: list[str] | None = None
    auto_continue: bool | None = None
    status: Literal["active", "paused", "budget_limited", "complete", "unmet", "cleared"] | None = None
    evidence: str | None = Field(default=None, max_length=4000)
    blocker: str | None = Field(default=None, max_length=4000)
    stop_reason: str | None = Field(default=None, max_length=200)


class CheckpointRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    next_step: str = Field(default="", max_length=2000)


@router.get("")
async def get_goal(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_conversation(db, session_id, user)
    goal = await get_current_goal(db, session_id)
    return {"goal": goal_to_dict(goal) if goal else None}


@router.post("")
async def post_goal(
    session_id: str,
    req: CreateGoalRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    try:
        goal = await create_goal(
            db,
            session_id=session_id,
            user_id=user.id,
            objective=req.objective,
            execution_model=req.execution_model,
            execution_provider=req.execution_provider,
            execution_agent=req.execution_agent,
            reasoning_effort=req.reasoning_effort,
            success_criteria=req.success_criteria,
            constraints=req.constraints,
            auto_continue=req.auto_continue,
            token_budget=req.token_budget,
            max_auto_turns=req.max_auto_turns,
        )
        await db.commit()
        await db.refresh(goal)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = goal_to_dict(goal)
    await _emit_goal_event(request, session_id, EventType.GOAL_CREATED, snapshot)
    return {"goal": snapshot}


@router.patch("")
async def patch_goal(
    session_id: str,
    req: UpdateGoalRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    goal = await get_current_goal(db, session_id) or await get_latest_goal(db, session_id)
    if not goal:
        raise HTTPException(status_code=404, detail="No goal for this session")
    if goal.status in {"complete", "cleared"}:
        raise HTTPException(status_code=409, detail="Closed goals cannot be updated")
    try:
        await update_goal(db, goal, **req.model_dump(exclude_unset=True))
        await db.commit()
        await db.refresh(goal)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.status in {"paused", "cleared", "complete", "unmet"}:
        try:
            from crabagent.core.goals.scheduler import cancel_goal_continuation

            cancel_goal_continuation(session_id)
        except Exception:
            pass
    snapshot = goal_to_dict(goal)
    event_type = EventType.GOAL_STATUS_CHANGED if req.status is not None else EventType.GOAL_UPDATED
    await _emit_goal_event(request, session_id, event_type, snapshot)
    return {"goal": snapshot}


@router.post("/checkpoint")
async def post_checkpoint(
    session_id: str,
    req: CheckpointRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)
    goal = await get_current_goal(db, session_id)
    if not goal:
        raise HTTPException(status_code=404, detail="No open goal for this session")
    try:
        checkpoint = await checkpoint_goal(db, goal, req.summary, req.next_step)
        await db.commit()
        await db.refresh(goal)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    snapshot = goal_to_dict(goal)
    checkpoint_data = {"id": checkpoint.id, "summary": checkpoint.summary, "next_step": checkpoint.next_step}
    await _emit_goal_event(request, session_id, EventType.GOAL_CHECKPOINT, snapshot, checkpoint=checkpoint_data)
    return {"goal": snapshot, "checkpoint": checkpoint_data}


@router.get("/history")
async def get_goal_history(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_conversation(db, session_id, user)
    goal = await get_current_goal(db, session_id)
    if not goal:
        return {"goal": None, "events": [], "checkpoints": []}
    events = (
        (await db.execute(select(GoalEvent).where(GoalEvent.goal_id == goal.id).order_by(GoalEvent.id.desc())))
        .scalars()
        .all()
    )
    checkpoints = (
        (
            await db.execute(
                select(GoalCheckpoint).where(GoalCheckpoint.goal_id == goal.id).order_by(GoalCheckpoint.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "goal": goal_to_dict(goal),
        "events": [
            {"type": e.event_type, "detail": e.detail, "data": e.data, "created_at": e.created_at.isoformat()}
            for e in events
        ],
        "checkpoints": [
            {"id": c.id, "summary": c.summary, "next_step": c.next_step, "created_at": c.created_at.isoformat()}
            for c in checkpoints
        ],
    }
