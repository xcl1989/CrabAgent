from __future__ import annotations

import logging
import time

from sqlalchemy import select

from crabagent.core.database import AgentProfile, async_session_factory

logger = logging.getLogger(__name__)

_registry_cache: list[dict] = []
_registry_loaded = False


async def load_agent_registry() -> list[dict]:
    global _registry_cache, _registry_loaded
    if _registry_loaded:
        return _registry_cache
    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentProfile).where(AgentProfile.enabled.is_(True)).order_by(AgentProfile.name)
        )
        rows = result.scalars().all()
        _registry_cache = [
            {
                "name": r.name,
                "display_name": r.display_name or r.name,
                "role": r.role,
                "goal": r.goal,
                "backstory": r.backstory or "",
                "model": r.model or "",
                "allow_delegation": r.allow_delegation,
            }
            for r in rows
        ]
    _registry_loaded = True
    return _registry_cache


def invalidate_cache():
    global _registry_loaded
    _registry_loaded = False


async def get_agent(name: str) -> dict | None:
    agents = await load_agent_registry()
    for a in agents:
        if a["name"] == name:
            return a
    return None


def _build_system_prompt(agent_def: dict) -> str:
    parts = [
        f"Role: {agent_def['role']}",
        f"Goal: {agent_def['goal']}",
    ]
    if agent_def.get("backstory"):
        parts.append(f"Backstory: {agent_def['backstory']}")
    parts.append(
        "Complete the task assigned to you. Be thorough and provide clear results. "
        "Do NOT ask questions to the user — you must work independently. "
        "When you finish, provide a complete summary of your findings."
    )
    return "\n".join(parts)


async def spawn_sub_agent(
    agent_name: str,
    task: str,
    parent_context,
) -> str:
    """Spawn a sub-agent and run it. Returns the result text."""
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.loop import run_agent
    from crabagent.core.agent.tools.registry import ToolRegistry
    from crabagent.core.event import AgentEvent, EventType

    agent_def = await get_agent(agent_name)
    if not agent_def:
        return f"Error: agent '{agent_name}' not found"

    sub_registry = ToolRegistry()

    for name, tool in parent_context.tool_registry._tools.items():
        if name in ("delegate_task", "list_agents", "handoff_to", "ask_question"):
            continue
        sub_registry._tools[name] = tool

    sub_context = AgentContext(
        workspace=parent_context.workspace,
        tool_registry=sub_registry,
        max_iterations=min(parent_context.max_iterations, 30),
        model=agent_def["model"] or parent_context.model,
        provider_name=parent_context.provider_name,
        system_prompt=_build_system_prompt(agent_def),
    )

    sub_context.confirm_callback = None

    sub_id = f"{agent_name}_{int(time.time() * 1000)}"

    await parent_context.event_bus.emit(AgentEvent(
        type=EventType.SUB_AGENT_START,
        data={
            "sub_agent_id": sub_id, "agent_name": agent_name,
            "display_name": agent_def["display_name"], "task": task[:200],
        },
    ))

    async def _bridge_events(event: AgentEvent):
        if event.type in (EventType.TEXT_DELTA,):
            await parent_context.event_bus.emit(AgentEvent(
                type=EventType.SUB_AGENT_TEXT_DELTA,
                data={
                    "sub_agent_id": sub_id, "agent_name": agent_name,
                    "text": event.data.get("text", ""),
                    "role": event.data.get("role", ""),
                },
            ))
        elif event.type in (EventType.TOOL_CALL,):
            await parent_context.event_bus.emit(AgentEvent(
                type=EventType.SUB_AGENT_TOOL_CALL,
                data={
                    "sub_agent_id": sub_id, "agent_name": agent_name,
                    "name": event.data.get("name", ""),
                    "arguments": event.data.get("arguments", {}),
                    "id": event.data.get("id", ""),
                },
            ))
        elif event.type in (EventType.TOOL_RESULT,):
            await parent_context.event_bus.emit(AgentEvent(
                type=EventType.SUB_AGENT_TOOL_RESULT,
                data={
                    "sub_agent_id": sub_id, "agent_name": agent_name,
                    "name": event.data.get("name", ""),
                    "result": event.data.get("result", "")[:500],
                },
            ))

    sub_context.event_bus.subscribe(_bridge_events)

    try:
        t0 = time.time()
        await run_agent(sub_context, task)
        elapsed = round(time.time() - t0, 1)

        last_text = ""
        for msg in reversed(sub_context.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_text = msg["content"]
                break

        await parent_context.event_bus.emit(AgentEvent(
            type=EventType.SUB_AGENT_END,
            data={
                "sub_agent_id": sub_id,
                "agent_name": agent_name,
                "display_name": agent_def["display_name"],
                "elapsed": elapsed,
                "tokens": sub_context.total_tokens,
                "iterations": sub_context.iteration,
                "result": last_text,
            },
        ))

        return last_text or "(sub-agent produced no output)"
    except Exception as e:
        logger.exception("Sub-agent %s failed", agent_name)
        await parent_context.event_bus.emit(AgentEvent(
            type=EventType.SUB_AGENT_ERROR,
            data={"sub_agent_id": sub_id, "agent_name": agent_name, "error": str(e)},
        ))
        return f"Error: sub-agent '{agent_name}' failed: {e}"
    finally:
        browser_mgr = sub_context.metadata.get("_browser_manager")
        if browser_mgr:
            try:
                await browser_mgr.close()
            except Exception:
                pass
        mcp_mgr = sub_context.metadata.get("_mcp_manager")
        if mcp_mgr:
            try:
                await mcp_mgr.stop_all()
            except Exception:
                pass
