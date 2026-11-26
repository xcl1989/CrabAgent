from __future__ import annotations

from crabagent.core.event import AgentEvent, EventType
from crabagent.core.goals.service import checkpoint_goal, get_current_goal, goal_to_dict, update_goal

# An auto-continuing goal may not be declared ``unmet`` before this many
# turns: agents tend to give up on first friction, and the user asked for a
# goal precisely because they want it driven to completion.
_UNMET_MIN_TURNS = 2


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
                "progress": {"type": "string", "description": "What was completed or learned."},
                "next_step": {"type": "string", "description": "The next concrete unfinished step."},
            },
            "required": ["progress"],
        },
    )
    async def checkpoint_goal_tool(progress: str, next_step: str = "", context=None):
        from crabagent.core.database import async_session_factory

        if context is not None:
            context.metadata["_goal_checkpoint_updated"] = True
        async with async_session_factory() as db:
            goal = await get_current_goal(db, session_id)
            if not goal:
                return "Error: no active goal for this session"
            checkpoint = await checkpoint_goal(db, goal, progress, next_step)
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
            "Close the active goal with a terminal status. Completing requires concrete verification "
            "evidence; unmet requires a concrete blocker. Pausing or resuming is a user action — "
            "do not set those here."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["complete", "unmet"],
                    "description": "complete = every success criterion is verified; unmet = blocked.",
                },
                "evidence": {"type": "string", "description": "Verification evidence required for complete."},
                "blocker": {"type": "string", "description": "Concrete blocker required for unmet."},
                "stop_reason": {"type": "string"},
            },
            "required": ["status"],
        },
    )
    async def update_goal_tool(status: str, evidence: str = "", blocker: str = "", stop_reason: str = "", context=None):
        from crabagent.core.database import async_session_factory

        if status not in ("complete", "unmet"):
            return (
                "Error: only 'complete' and 'unmet' are available to the agent. "
                "Pausing or resuming a goal is a user action."
            )
        async with async_session_factory() as db:
            goal = await get_current_goal(db, session_id)
            if not goal:
                return "Error: no active goal for this session"
            if status == "unmet" and goal.auto_continue and (goal.auto_turns or 0) < _UNMET_MIN_TURNS:
                # Early give-up guard: the agent has barely started. Ask it to
                # try a workaround or request what it needs via ask_question
                # instead of surrendering on first friction.
                return (
                    f"Error: the goal has only run {goal.auto_turns or 0} turn(s). Before declaring it "
                    "unmet, try a workaround (mock, skip marker, alternative path). If you truly need "
                    "something from the user, call ask_question and wait — the goal stays active."
                )
            try:
                await update_goal(db, goal, status=status, evidence=evidence, blocker=blocker, stop_reason=stop_reason)
            except ValueError as exc:
                return f"Error: {exc}"
            await db.commit()
            snapshot = goal_to_dict(goal)
        if context is not None:
            context.metadata["_goal_status_updated"] = True
        await context.event_bus.emit(AgentEvent(type=EventType.GOAL_STATUS_CHANGED, data={"goal": snapshot}))
        return {"goal": snapshot}
