from __future__ import annotations

import json as _json
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
        _registry_cache = []
        for r in rows:
            tools_list = []
            if r.tools:
                try:
                    tools_list = _json.loads(r.tools)
                except Exception:
                    pass
            _registry_cache.append({
                "name": r.name,
                "display_name": r.display_name or r.name,
                "role": r.role,
                "goal": r.goal,
                "backstory": r.backstory or "",
                "model": r.model or "",
                "allow_delegation": r.allow_delegation,
                "icon": r.icon or "",
                "is_default": r.is_default,
                "tools": tools_list,
            })
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


_MEMORY_TOOLS = {"memory_save", "memory_recall", "memory_replace", "memory_list", "memory_forget"}
_SHARED_TOOLS = {"shared_get", "shared_put", "shared_list"}
_DELEGATION_TOOLS = {
    "delegate_task", "delegate_parallel", "list_agents",
    "handoff_to", "ask_question", "request_help",
}


def _build_system_prompt(
    agent_def: dict,
    has_shared: bool = False,
    can_request_help: bool = False,
) -> str:
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
    if has_shared:
        parts.append(
            "You have access to a shared team workspace. "
            "Use `shared_put(key, value)` to save important findings. "
            "Other team members can read them with `shared_get(key)`. "
            "Use `shared_list()` to see all shared notes. "
            "Always save your key findings before finishing."
        )
    if can_request_help:
        parts.append(
            "If you encounter a task that requires different expertise, "
            "you can use `request_help(agent_name, question)` "
            "to ask another agent for assistance."
        )
    return "\n".join(parts)


async def build_team_prompt() -> str:
    agents = await load_agent_registry()
    if not agents:
        return ""
    lines = [
        "## Agent Team",
        "",
        "You have a team of specialized agents you can delegate tasks to. "
        "Use them when a task benefits from specialized expertise or parallel execution.",
        "",
        "### Available Agents",
        "",
    ]
    for a in agents:
        tools_info = ""
        if a.get("tools"):
            tools_info = f" Tools: {', '.join(a['tools'])}"
        lines.append(
            f"- **{a['display_name']}** (`{a['name']}`): "
            f"{a['role']}. {a['goal']}{tools_info}"
        )
    lines.extend([
        "",
        "### Delegation Tools",
        "",
        "- `list_agents`: List all available agents with details",
        "- `delegate_task(agent_name, task)`: Delegate a task to a specific agent",
        "- `delegate_parallel(tasks)`: Delegate tasks to multiple agents simultaneously",
        "- `handoff_to(agent_name, summary)`: Hand off work to another agent with context",
        "- `run_pipeline(steps)`: Run a multi-step pipeline with agent dependencies",
        "",
        "### Shared Workspace",
        "",
        "- `shared_put(key, value)`: Save findings to shared workspace",
        "- `shared_get(key)`: Read findings from other agents",
        "- `shared_list()`: List all shared notes",
        "",
        "### When to Delegate",
        "",
        "- Web research, searching, browsing -> `researcher`",
        "- Data analysis, comparison, report generation -> `analyst`",
        "- Code writing, debugging, refactoring -> `coder`",
        "- Content writing, editing, translation -> `writer`",
        "- Multiple independent subtasks -> `delegate_parallel`",
        "- Complex multi-step task with dependencies -> `run_pipeline`",
        "",
    ])
    return "\n".join(lines)


async def _load_shared_context(session_id: str) -> str:
    if not session_id:
        return ""
    from crabagent.core.database import shared_memory_get_all
    items = await shared_memory_get_all(session_id)
    if not items:
        return ""
    lines = ["## Shared Team Knowledge", ""]
    for item in items:
        author_tag = f" (by {item['author']})" if item["author"] else ""
        lines.append(f"### {item['key']}{author_tag}")
        lines.append(item["value"])
        lines.append("")
    return "\n".join(lines)


async def build_memory_prompt(user_id: int) -> str:
    if not user_id:
        return ""
    from crabagent.core.database import agent_memory_get_by_type
    team_memories = await agent_memory_get_by_type(user_id, "team_knowledge", limit=10)
    if not team_memories:
        return ""
    total_chars = sum(len(m["content"]) for m in team_memories)
    if total_chars > 3000:
        team_memories = team_memories[:5]
    lines = ["## Team Knowledge", ""]
    for m in team_memories:
        cat = m["category"]
        lines.append(f"- **{m['key']}** ({cat}): {m['content']}")
    lines.append("")
    lines.append(
        "You can save new knowledge with `memory_save(memory_type='team', ...)`. "
        "When the user makes a choice or rejects an option, record it."
    )
    lines.append("")
    return "\n".join(lines)


def _extract_lesson(
    agent_name: str,
    iterations: int,
    max_iterations: int,
    task: str,
    result: str,
    used_shared: bool = False,
) -> dict | None:
    lesson = None
    if iterations >= max_iterations * 0.8:
        lesson = {
            "category": "failed_approach",
            "key": f"lesson:{agent_name}:high_iterations",
            "content": f"Task '{task[:80]}' used {iterations}/{max_iterations} iterations. Consider breaking complex tasks into smaller steps.",
            "importance": 0.6,
        }
    elif iterations <= max_iterations * 0.2 and result:
        lesson = {
            "category": "effective_strategy",
            "key": f"lesson:{agent_name}:efficient",
            "content": f"Task '{task[:80]}' completed efficiently in {iterations} steps.",
            "importance": 0.4,
        }
    if used_shared and result:
        lesson_tip = {
            "category": "tool_tip",
            "key": f"lesson:{agent_name}:shared_workspace",
            "content": f"Agent {agent_name} successfully used shared workspace for coordination.",
            "importance": 0.3,
        }
        if lesson:
            return lesson
        return lesson_tip
    return lesson


async def spawn_sub_agent(
    agent_name: str,
    task: str,
    parent_context,
    include_history: bool = False,
    max_depth: int = 1,
) -> str:
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.loop import run_agent
    from crabagent.core.agent.tools.registry import ToolRegistry
    from crabagent.core.event import AgentEvent, EventType

    agent_def = await get_agent(agent_name)
    if not agent_def:
        return f"Error: agent '{agent_name}' not found"

    sub_registry = ToolRegistry()

    agent_tools = agent_def.get("tools", [])
    current_depth = parent_context.metadata.get("_sub_agent_depth", 0)
    has_shared = False
    can_request_help = False

    if agent_tools:
        allowed = set(agent_tools) | _SHARED_TOOLS
        for name, tool in parent_context.tool_registry._tools.items():
            if name in _DELEGATION_TOOLS:
                continue
            if name in allowed:
                sub_registry._tools[name] = tool
        has_shared = bool(_SHARED_TOOLS & allowed)
    else:
        for name, tool in parent_context.tool_registry._tools.items():
            if name in _DELEGATION_TOOLS:
                continue
            sub_registry._tools[name] = tool
        has_shared = True

    for mname, mtool in parent_context.tool_registry._tools.items():
        if mname in _MEMORY_TOOLS and mname not in sub_registry._tools:
            sub_registry._tools[mname] = mtool

    if agent_def.get("allow_delegation") and current_depth < max_depth:
        parent_tools = parent_context.tool_registry._tools
        if "request_help" in parent_tools:
            sub_registry._tools["request_help"] = parent_tools["request_help"]
            can_request_help = True

    sub_context = AgentContext(
        workspace=parent_context.workspace,
        tool_registry=sub_registry,
        max_iterations=min(parent_context.max_iterations, 50),
        model=agent_def["model"] or parent_context.model,
        provider_name=parent_context.provider_name,
        system_prompt=_build_system_prompt(
            agent_def, has_shared=has_shared, can_request_help=can_request_help,
        ),
    )

    sub_context.confirm_callback = None
    sub_context.metadata["_sub_agent_name"] = agent_name
    sub_context.metadata["_sub_agent_depth"] = current_depth + 1

    parent_user_id = parent_context.metadata.get("user_id", 0)
    if parent_user_id:
        sub_context.metadata["user_id"] = parent_user_id

    session_id = parent_context.metadata.get("session_id", "")
    if session_id:
        sub_context.metadata["session_id"] = session_id

    agent_lessons = []
    if parent_user_id:
        try:
            from crabagent.core.database import agent_memory_get_by_agent
            agent_lessons = await agent_memory_get_by_agent(parent_user_id, agent_name, limit=5)
        except Exception:
            pass

    if agent_lessons:
        lesson_lines = ["## Your Past Lessons", ""]
        for lesson in agent_lessons:
            lesson_lines.append(f"- {lesson['content']}")
        lesson_lines.append("")
        sub_context.system_prompt += "\n\n" + "\n".join(lesson_lines)

    shared_context = await _load_shared_context(session_id)

    if include_history and parent_context.messages:
        recent = parent_context.messages[-20:]
        history_lines = ["## Previous Conversation Context", ""]
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "user" and content:
                history_lines.append(f"User: {content[:500]}")
            elif role == "assistant" and content:
                history_lines.append(f"Assistant: {content[:500]}")
        history_text = "\n".join(history_lines)
        prompt_parts = [history_text]
        if shared_context:
            prompt_parts.append(shared_context)
        prompt_parts.append(f"## Your Task\n{task}")
        sub_context.messages = [
            {"role": "user", "content": "\n\n".join(prompt_parts)}
        ]
    else:
        if shared_context:
            sub_context.messages = [
                {"role": "user", "content": f"{shared_context}\n\n## Your Task\n{task}"}
            ]

    import uuid as _uuid
    sub_id = f"{agent_name}_{_uuid.uuid4().hex[:8]}"

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
        elif event.type in (EventType.THINKING_DELTA,):
            await parent_context.event_bus.emit(AgentEvent(
                type=EventType.SUB_AGENT_TEXT_DELTA,
                data={
                    "sub_agent_id": sub_id, "agent_name": agent_name,
                    "text": event.data.get("text", ""),
                    "role": "thinking",
                },
            ))
        elif event.type in (EventType.THINKING_DONE,):
            pass
        elif event.type in (EventType.AGENT_ERROR,):
            await parent_context.event_bus.emit(AgentEvent(
                type=EventType.SUB_AGENT_ERROR,
                data={
                    "sub_agent_id": sub_id, "agent_name": agent_name,
                    "error": event.data.get("error", "unknown error"),
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

        if session_id and last_text:
            summary = last_text[:2000]
            try:
                from crabagent.core.database import shared_memory_put
                await shared_memory_put(
                    session_id,
                    f"findings:{agent_name}",
                    summary,
                    author=agent_name,
                )
            except Exception:
                logger.debug(
                    "Failed to auto-save shared memory for %s", agent_name,
                )

        if parent_user_id:
            try:
                lesson = _extract_lesson(
                    agent_name=agent_name,
                    iterations=sub_context.iteration,
                    max_iterations=sub_context.max_iterations,
                    task=task,
                    result=last_text,
                    used_shared=has_shared,
                )
                if lesson:
                    from crabagent.core.database import agent_memory_upsert
                    await agent_memory_upsert(
                        user_id=parent_user_id,
                        memory_type="agent_lesson",
                        agent_name=agent_name,
                        category=lesson["category"],
                        key=lesson["key"],
                        content=lesson["content"],
                        importance=lesson["importance"],
                        source_session=session_id,
                    )
            except Exception:
                logger.debug("Failed to extract lesson for %s", agent_name)

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

        sub_content = _json.dumps({
            "text": last_text,
            "agent_name": agent_name,
            "display_name": agent_def["display_name"],
            "elapsed": elapsed,
            "tokens": sub_context.total_tokens,
            "iterations": sub_context.iteration,
        }, ensure_ascii=False)

        pending = parent_context.metadata.setdefault(
            "_pending_sub_agent_messages", [],
        )
        pending.append({
            "role": "sub_agent",
            "content": sub_content,
            "name": agent_name,
        })

        return last_text or "(sub-agent produced no output)"
    except Exception as e:
        logger.exception("Sub-agent %s failed", agent_name)
        await parent_context.event_bus.emit(AgentEvent(
            type=EventType.SUB_AGENT_ERROR,
            data={
                "sub_agent_id": sub_id,
                "agent_name": agent_name,
                "error": str(e),
            },
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
