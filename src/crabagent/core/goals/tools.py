from __future__ import annotations

from crabagent.core.event import AgentEvent, EventType
from crabagent.core.goals.service import checkpoint_goal, get_current_goal, goal_to_dict, update_goal


def register_goal_tools(context, session_id: str, user_id: int) -> None:
    """Register goal tools on the per-request registry so they retain session scope."""

    @context.tool_registry.register(
        name="get_goal",
        description="Get the active session goal, its criteria, constraints, status, and latest checkpoint.",
        parameters={"type": "object", "properties": {}},
    )
    async def get_goal_tool(context=None):
        from crabagent.core.database import async_session_factory

        async with async_session_factory() as db:
            goal = await get_current_goal(db, session_id)
            return goal_to_dict(goal) if goal else {"goal": None}

    @context.tool_registry.register(
        name="checkpoint_goal",
        description="Record meaningful progress toward the active goal, including the next concrete step.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was completed or learned."},
                "next_step": {"type": "string", "description": "The next concrete unfinished step."},
            },
            "required": ["summary"],
        },
    )
    async def checkpoint_goal_tool(summary: str, next_step: str = "", context=None):
        from crabagent.core.database import async_session_factory

        if context is not None:
            context.metadata["_goal_checkpoint_updated"] = True
        async with async_session_factory() as db:
            goal = await get_current_goal(db, session_id)
            if not goal:
                return "Error: no active goal for this session"
            checkpoint = await checkpoint_goal(db, goal, summary, next_step)
            await db.commit()
            snapshot = goal_to_dict(goal)
        checkpoint_data = {"summary": checkpoint.summary, "next_step": checkpoint.next_step}
        await context.event_bus.emit(
            AgentEvent(type=EventType.GOAL_CHECKPOINT, data={"goal": snapshot, "checkpoint": checkpoint_data})
        )
        return {"goal": snapshot, "checkpoint": checkpoint_data}

    @context.tool_registry.register(
        name="update_goal",
        description=(
            "Update the active goal status. Completing requires concrete verification evidence; "
            "unmet requires a concrete blocker."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "paused", "complete", "unmet"]},
                "evidence": {"type": "string", "description": "Verification evidence required for complete."},
                "blocker": {"type": "string", "description": "Concrete blocker required for unmet."},
                "stop_reason": {"type": "string"},
            },
            "required": ["status"],
        },
    )
    async def update_goal_tool(status: str, evidence: str = "", blocker: str = "", stop_reason: str = "", context=None):
        from crabagent.core.database import async_session_factory

        if context is not None:
            context.metadata["_goal_status_updated"] = True
        async with async_session_factory() as db:
            goal = await get_current_goal(db, session_id)
            if not goal:
                return "Error: no active goal for this session"
            try:
                await update_goal(db, goal, status=status, evidence=evidence, blocker=blocker, stop_reason=stop_reason)
            except ValueError as exc:
                return f"Error: {exc}"
            await db.commit()
            snapshot = goal_to_dict(goal)
        await context.event_bus.emit(AgentEvent(type=EventType.GOAL_STATUS_CHANGED, data={"goal": snapshot}))
        return {"goal": snapshot}
