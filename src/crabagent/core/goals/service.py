from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import Goal, GoalCheckpoint, GoalEvent

OPEN_STATUSES = {"active", "paused", "budget_limited", "unmet"}
CLOSED_STATUSES = {"complete", "cleared"}
VALID_STATUSES = OPEN_STATUSES | CLOSED_STATUSES


def _as_list(value: str | list[str] | None) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return [item.strip() for item in value or [] if item and item.strip()]


def goal_to_dict(goal: Goal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "session_id": goal.session_id,
        "objective": goal.objective,
        "execution_model": goal.execution_model or "",
        "execution_provider": goal.execution_provider or "",
        "execution_agent": goal.execution_agent or "",
        "reasoning_effort": goal.reasoning_effort or "",
        "success_criteria": goal.success_criteria or [],
        "constraints": goal.constraints or [],
        "status": goal.status,
        "auto_continue": goal.auto_continue,
        "token_budget": goal.token_budget,
        "tokens_used": goal.tokens_used,
        "max_auto_turns": goal.max_auto_turns,
        "auto_turns": goal.auto_turns,
        "completion_evidence": goal.completion_evidence or "",
        "blocker": goal.blocker or "",
        "latest_checkpoint": goal.latest_checkpoint or "",
        "next_step": goal.next_step or "",
        "stop_reason": goal.stop_reason or "",
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
        "closed_at": goal.closed_at.isoformat() if goal.closed_at else None,
    }


async def get_current_goal(db: AsyncSession, session_id: str) -> Goal | None:
    result = await db.execute(
        select(Goal)
        .where(Goal.session_id == session_id, Goal.status.not_in(CLOSED_STATUSES))
        .order_by(Goal.updated_at.desc(), Goal.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_goal(db: AsyncSession, session_id: str) -> Goal | None:
    result = await db.execute(
        select(Goal).where(Goal.session_id == session_id).order_by(Goal.updated_at.desc(), Goal.id.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def create_goal(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: int,
    objective: str,
    execution_model: str = "",
    execution_provider: str = "",
    execution_agent: str = "",
    reasoning_effort: str = "",
    success_criteria: str | list[str] | None = None,
    constraints: str | list[str] | None = None,
    auto_continue: bool = False,
    token_budget: int | None = None,
    max_auto_turns: int | None = None,
) -> Goal:
    objective = objective.strip()
    if not objective:
        raise ValueError("Goal objective must not be empty")
    if await get_current_goal(db, session_id):
        raise ValueError("This session already has an open goal")
    if auto_continue and max_auto_turns is None:
        max_auto_turns = 10
    if auto_continue and token_budget is None:
        token_budget = 80_000
    goal = Goal(
        session_id=session_id,
        user_id=user_id,
        objective=objective,
        execution_model=execution_model.strip(),
        execution_provider=execution_provider.strip(),
        execution_agent=execution_agent.strip(),
        reasoning_effort=reasoning_effort.strip(),
        success_criteria=_as_list(success_criteria),
        constraints=_as_list(constraints),
        auto_continue=auto_continue,
        token_budget=token_budget,
        max_auto_turns=max_auto_turns,
    )
    db.add(goal)
    await db.flush()
    await record_event(db, goal, "created", "Goal created")
    return goal


async def record_event(db: AsyncSession, goal: Goal, event_type: str, detail: str, data: dict | None = None) -> None:
    db.add(GoalEvent(goal_id=goal.id, event_type=event_type, detail=detail, data=data))


async def checkpoint_goal(db: AsyncSession, goal: Goal, summary: str, next_step: str = "") -> GoalCheckpoint:
    summary = summary.strip()
    if not summary:
        raise ValueError("Checkpoint summary must not be empty")
    checkpoint = GoalCheckpoint(goal_id=goal.id, summary=summary, next_step=next_step.strip())
    db.add(checkpoint)
    goal.latest_checkpoint = summary
    if next_step.strip():
        goal.next_step = next_step.strip()
    goal.updated_at = datetime.now()
    await record_event(db, goal, "checkpoint", summary, {"next_step": checkpoint.next_step})
    return checkpoint


async def account_goal_usage(db: AsyncSession, goal: Goal, tokens_used: int) -> bool:
    """Record one execution turn and return whether the goal reached a safety limit."""
    goal.tokens_used += max(0, tokens_used)
    goal.auto_turns += 1
    goal.updated_at = datetime.now()
    limited = (goal.token_budget is not None and goal.tokens_used >= goal.token_budget) or (
        goal.max_auto_turns is not None and goal.auto_turns >= goal.max_auto_turns
    )
    if limited:
        goal.status = "budget_limited"
        goal.stop_reason = "Token budget or automatic turn limit reached"
        await record_event(db, goal, "limited", goal.stop_reason)
    else:
        await record_event(db, goal, "usage", f"Automatic turn {goal.auto_turns} completed")
    return limited


async def update_goal(
    db: AsyncSession,
    goal: Goal,
    *,
    objective: str | None = None,
    success_criteria: str | list[str] | None = None,
    constraints: str | list[str] | None = None,
    auto_continue: bool | None = None,
    status: str | None = None,
    evidence: str | None = None,
    blocker: str | None = None,
    stop_reason: str | None = None,
) -> Goal:
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid goal status")
        if status == "complete" and not (evidence or "").strip():
            raise ValueError("Completion requires verification evidence")
        if status == "unmet" and not (blocker or "").strip():
            raise ValueError("Unmet goals require a concrete blocker")
        goal.status = status
        if status in CLOSED_STATUSES:
            goal.closed_at = datetime.now()
    if objective is not None:
        objective = objective.strip()
        if not objective:
            raise ValueError("Goal objective must not be empty")
        goal.objective = objective
        goal.completion_evidence = ""
    if success_criteria is not None:
        goal.success_criteria = _as_list(success_criteria)
    if constraints is not None:
        goal.constraints = _as_list(constraints)
    if auto_continue is not None:
        goal.auto_continue = auto_continue
    if evidence is not None:
        goal.completion_evidence = evidence.strip()
    if blocker is not None:
        goal.blocker = blocker.strip()
    if stop_reason is not None:
        goal.stop_reason = stop_reason.strip()
    goal.updated_at = datetime.now()
    await record_event(db, goal, "updated", f"Goal status: {goal.status}")
    return goal


def goal_finalization_required(metadata: dict[str, Any]) -> bool:
    """Return whether a successful goal run ended without a terminal status."""
    return (
        bool(metadata.get("goal_id"))
        and not metadata.get("_run_error")
        and not metadata.get("_agent_error")
        and not metadata.get("_goal_status_updated")
    )


def automatic_completion_evidence(summary: str) -> str | None:
    """Accept completion only when the final reply states both outcome and verification."""
    clean = re.sub(r"\s+", " ", summary).strip()
    if not clean:
        return None
    completed = re.search(r"(已完成|完成了|已实现|已修复|已处理|完成构建)", clean)
    verified = re.search(r"(测试.*通过|\d+\s+passed|构建成功|build ok|已验证|验证.*通过|diff --check.*通过)", clean, re.I)
    if not (completed and verified):
        return None
    return clean[:1200]


def finalization_checkpoint(summary: str) -> tuple[str, str]:
    """Keep an unfinished goal explicit when the agent ended without closing it."""
    clean = re.sub(r"\s+", " ", summary).strip()
    if len(clean) > 240:
        clean = clean[:237].rstrip() + "..."
    return (
        "Agent completed its response without recording a final goal status.",
        "Review the final response and call update_goal with verified completion evidence, or record the remaining work.",
    ) if not clean else (
        "Agent response ended without recording a final goal status: " + clean,
        "Review the final response and call update_goal with verified completion evidence, or record the remaining work.",
    )


def goal_prompt(goal: Goal) -> str:
    criteria = "\n".join(f"- {item}" for item in (goal.success_criteria or [])) or "- No explicit criteria provided."
    constraints = "\n".join(f"- {item}" for item in (goal.constraints or [])) or "- None."
    checkpoint = goal.latest_checkpoint or "No checkpoint yet."
    return "\n\n".join(
        [
            "## Active Goal",
            f"Objective:\n{goal.objective}",
            f"Success criteria:\n{criteria}",
            f"Constraints:\n{constraints}",
            f"Latest checkpoint:\n{checkpoint}",
            "Rules:\n"
            "- Work toward this goal while responding to the user.\n"
            "- Use checkpoint_goal after meaningful progress.\n"
            "- Before the final user-facing response, you MUST call update_goal with status complete, "
            "paused, or unmet; do not leave a completed work turn active.\n"
            "- Never claim completion without verifying every applicable success criterion.\n"
            "- Use update_goal with status complete only with concrete verification evidence.\n"
            "- Use status unmet only for a concrete blocker.",
        ]
    )
