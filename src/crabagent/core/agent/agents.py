from __future__ import annotations

import json as _json
import logging
import time

from sqlalchemy import select

from crabagent.core.agent.reflect import (
    classify_task as _classify_task,
)
from crabagent.core.agent.reflect import (
    llm_reflect_lesson as _llm_reflect_lesson,
)
from crabagent.core.agent.reflect import (
    rule_extract_lesson as _rule_extract_lesson,
)
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
            tool_perms = {}
            if r.tool_permissions:
                try:
                    tool_perms = _json.loads(r.tool_permissions)
                except Exception:
                    pass
            _registry_cache.append(
                {
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
                    "tool_permissions": tool_perms,
                }
            )
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
    "delegate_task",
    "delegate_parallel",
    "list_agents",
    "handoff_to",
    "ask_question",
    "request_help",
}


def get_memory_tools() -> set[str]:
    return _MEMORY_TOOLS


def get_shared_tools() -> set[str]:
    return _SHARED_TOOLS


def get_delegation_tools() -> set[str]:
    return _DELEGATION_TOOLS


def _translate_agent_field(agent_name: str, field: str, original: str, locale: str) -> str:
    """Return translated agent field if available, otherwise the original."""
    from crabagent.core.i18n import t

    key = f"agents.{agent_name}.{field}"
    translated = t(key, locale)
    # t() returns the key itself when translation is not found.
    # In that case, fall back to the original value from agent_def.
    if translated == key:
        return original
    return translated or original


def build_agent_switch_msg(agent_def: dict, locale: str = "en") -> dict:
    from crabagent.core.i18n import t

    agent_name = agent_def["name"]
    icon = agent_def.get("icon", "")
    _d = _translate_agent_field(agent_name, "display_name", agent_def["display_name"], locale)
    _r = _translate_agent_field(agent_name, "role", agent_def.get("role", ""), locale)
    _g = _translate_agent_field(agent_name, "goal", agent_def["goal"], locale)
    _b = _translate_agent_field(agent_name, "backstory", agent_def.get("backstory", ""), locale)
    lines = [
        t("agent_switch.header", locale, icon=icon, display_name=_d),
        t("agent_switch.role", locale, role=_r),
        t("agent_switch.goal", locale, goal=_g),
    ]
    if _b:
        lines.append(t("agent_switch.backstory", locale, backstory=_b))
    lines.append(t("agent_switch.footer", locale))
    return {"role": "user", "content": "\n".join(lines), "agent": agent_name}


def _build_system_prompt(
    agent_def: dict,
    has_shared: bool = False,
    can_request_help: bool = False,
    locale: str = "en",
) -> str:
    from crabagent.core.i18n import t

    agent_name = agent_def["name"]
    _r = _translate_agent_field(agent_name, "role", agent_def.get("role", ""), locale)
    _g = _translate_agent_field(agent_name, "goal", agent_def.get("goal", ""), locale)
    _b = _translate_agent_field(agent_name, "backstory", agent_def.get("backstory", ""), locale)
    parts = [
        t("agent_system.role", locale, role=_r),
        t("agent_system.goal", locale, goal=_g),
    ]
    if _b:
        parts.append(t("agent_system.backstory", locale, backstory=_b))
    parts.append(t("agent_system.task_instruction", locale))
    if has_shared:
        parts.append(t("agent_system.shared_instruction", locale))
    if can_request_help:
        parts.append(t("agent_system.help_instruction", locale))
    return "\n".join(parts)


def _load_list(locale: str, key: str) -> list[str]:
    """Load a list translation by dot-notation key, falling back to English."""
    from crabagent.core.i18n import _load

    for loc in (locale, "en"):
        data = _load(loc)
        parts = key.split(".")
        node = data
        for p in parts:
            if isinstance(node, dict):
                node = node.get(p)
            else:
                node = None
                break
        if isinstance(node, list):
            return node
    return []


async def build_team_prompt(locale: str = "en") -> str:
    from crabagent.core.i18n import t

    agents = await load_agent_registry()
    if not agents:
        return ""
    lines = [
        t("team_prompt.title", locale),
        "",
        t("team_prompt.intro", locale),
        "",
        t("team_prompt.available_agents", locale),
        "",
    ]
    for a in agents:
        perms = a.get("tool_permissions", {})
        denied = [k for k, v in perms.items() if v == "deny"]
        perm_info = ""
        if denied:
            denied_str = ", ".join(denied)
            perm_info = " " + t("team_prompt.restricted", locale, tools=denied_str)
        # Use translated agent fields when available (fall back to original if no i18n entry)
        agent_name = a["name"]
        _dk = f"agents.{agent_name}.display_name"
        _rk = f"agents.{agent_name}.role"
        _gk = f"agents.{agent_name}.goal"
        _dt = t(_dk, locale)
        _rt = t(_rk, locale)
        _gt = t(_gk, locale)
        display_name = _dt if _dt != _dk else a["display_name"]
        role = _rt if _rt != _rk else a["role"]
        goal = _gt if _gt != _gk else a["goal"]
        lines.append(f"- **{display_name}** (`{agent_name}`): {role}. {goal}{perm_info}")
    lines.extend(
        [
            "",
            t("team_prompt.delegation_tools", locale),
            "",
        ]
    )
    for key in ("list_agents", "plan_task", "delegate_task", "delegate_parallel", "handoff_to", "run_pipeline"):
        lines.append(f"- {t(f'team_prompt.tools.{key}', locale)}")
    lines.extend(
        [
            "",
            t("team_prompt.shared_workspace", locale),
            "",
        ]
    )
    for key in ("shared_put", "shared_get", "shared_list"):
        lines.append(f"- {t(f'team_prompt.shared.{key}', locale)}")
    lines.extend(
        [
            "",
            t("team_prompt.when_to_delegate", locale),
            "",
        ]
    )
    when_list = _load_list(locale, "team_prompt.when")
    for item in when_list:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


async def _load_shared_context(session_id: str, locale: str = "en") -> str:
    from crabagent.core.i18n import t

    if not session_id:
        return ""
    from crabagent.core.database import shared_memory_get_all

    items = await shared_memory_get_all(session_id)
    if not items:
        return ""
    lines = [t("shared_context.title", locale), ""]
    for item in items:
        author_tag = f" (by {item['author']})" if item["author"] else ""
        lines.append(f"### {item['key']}{author_tag}")
        lines.append(item["value"])
        lines.append("")
    return "\n".join(lines)


async def build_memory_prompt(user_id: int, query: str = "", locale: str = "en") -> str:
    if not user_id:
        return ""
    from crabagent.core.config import settings
    from crabagent.core.database import (
        agent_memory_get_by_type,
        agent_memory_search_vector,
    )
    from crabagent.core.i18n import t

    parts: list[str] = []

    team_memories = await agent_memory_get_by_type(user_id, "team", limit=10)
    if team_memories:
        total_chars = sum(len(m["content"]) for m in team_memories)
        if total_chars > 3000:
            team_memories = team_memories[:5]
        lines = [t("memory_prompt.team_knowledge_title", locale), ""]
        for m in team_memories:
            cat = m["category"]
            lines.append(f"- **{m['key']}** ({cat}): {m['content']}")
        lines.append("")
        lines.append(t("memory_prompt.save_instruction", locale))
        lines.append("")
        parts.append("\n".join(lines))

    # NEW (v0.9): query-aware recall. Searches both lessons and user_preferences
    # by keyword; injects top-K relevant to the current user message.
    max_inject = int(getattr(settings, "memory_max_inject", 5))
    if query and getattr(settings, "memory_auto_recall", True) and max_inject > 0:
        try:
            # Prefer vector search; falls back to LIKE automatically
            related = await agent_memory_search_vector(
                user_id,
                query[:200],
                memory_type="",
                limit=max_inject,
                fallback=True,
            )
        except Exception:
            related = []
        if related:
            # Prefer user_preferences first (they shape behaviour), then lessons
            prefs = [m for m in related if m.get("memory_type") == "user_preference"]
            lessons = [m for m in related if m.get("memory_type") != "user_preference"]
            ordered = prefs[:3] + lessons[: max_inject - len(prefs[:3])]
            if ordered:
                lines = ["## Related Memories (auto-recalled)", ""]
                for m in ordered:
                    mtype = m.get("memory_type", "lesson")
                    agent_tag = f" [{m.get('agent_name')}]" if m.get("agent_name") else ""
                    sim_tag = ""
                    if "_similarity" in m:
                        sim_tag = f", sim={m['_similarity']:.2f}"
                    lines.append(
                        f"- **{m['key']}** ({mtype}{agent_tag}, "
                        f"imp={m.get('importance', 0.5):.1f}{sim_tag}): {m['content']}"
                    )
                lines.append("")
                parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else ""


async def inject_agent_lessons(
    system_prompt: str,
    user_id: int,
    agent_name: str,
    task_hint: str = "",
) -> str:
    """Append a '## Your Past Experiences' block to ``system_prompt`` if the
    agent has previously persisted lessons.

    Used by both sub-agent delegation (agents.py) and the main agent
    (prompt.py). When ``task_hint`` is given, we additionally query for
    lessons whose content/key matches the hint.

    P3: Supports cross-agent lesson sharing — if own lessons < limit,
    supplements with high-quality lessons from other agents.
    """

    if not user_id or not agent_name:
        return system_prompt
    from crabagent.core.database import (
        agent_memory_get_by_agent,
        agent_memory_search_vector,
    )

    lessons: list[dict] = []
    try:
        lessons = await agent_memory_get_by_agent(user_id, agent_name, limit=5)
    except Exception:
        logger.debug("Failed to load agent lessons for %s", agent_name, exc_info=True)

    if task_hint and len(lessons) < 7:
        try:
            similar = await agent_memory_search_vector(
                user_id,
                task_hint[:120],
                memory_type="agent_lesson",
                limit=3,
                fallback=True,
            )
            existing_keys = {item["key"] for item in lessons}
            for s in similar:
                if s["key"] not in existing_keys and s.get("agent_name") == agent_name:
                    lessons.append(s)
                    existing_keys.add(s["key"])
        except Exception:
            pass

    # P3: Cross-agent sharing — supplement with high-quality general lessons
    if len(lessons) < 5:
        try:
            existing_keys = {item["key"] for item in lessons}
            general = await agent_memory_search_vector(
                user_id,
                task_hint or "general best practices",
                memory_type="agent_lesson",
                limit=8,
                fallback=True,
            )
            for g in general:
                if g["key"] in existing_keys:
                    continue
                if g.get("agent_name") in (agent_name, "", None):
                    continue  # skip own or already-loaded
                if g.get("importance", 0) >= 0.7 and g.get("_similarity", 0) >= 0.4:
                    lessons.append(g)
                    existing_keys.add(g["key"])
                    if len(lessons) >= 7:
                        break
        except Exception:
            pass

    if not lessons:
        return system_prompt

    by_cat: dict[str, list[str]] = {}
    for lesson in lessons:
        cat = lesson.get("category", "effective_strategy") or "effective_strategy"
        source = lesson.get("source", "")
        tag = "⚠️" if cat == "failed_approach" else ("🧠" if source == "llm" else "📋")
        by_cat.setdefault(cat, []).append(f"{tag} {lesson['content']}")

    lines = [system_prompt or "", "\n\n## Your Past Experiences\n"]
    lines.append("Use these to guide your approach. Avoid repeating past mistakes.\n")
    if "failed_approach" in by_cat:
        lines.append("### Pitfalls to Avoid")
        for item in by_cat["failed_approach"]:
            lines.append(f"- {item}")
        lines.append("")
    if "effective_strategy" in by_cat:
        lines.append("### What Worked Before")
        for item in by_cat["effective_strategy"]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


_running_sub_agents: dict[str, dict] = {}
_COMPLETED_TTL = 30 * 60


def get_running_subs(session_id: str) -> dict[str, dict]:
    now = time.time()
    result = {}
    for k, v in _running_sub_agents.items():
        completed_at = v.get("completed_at")
        if completed_at and now - completed_at > _COMPLETED_TTL:
            continue
        if v.get("session_id") == session_id and not completed_at:
            result[k] = v
    return result


def get_all_session_subs(session_id: str) -> dict[str, dict]:
    now = time.time()
    result = {}
    expired = []
    for k, v in _running_sub_agents.items():
        completed_at = v.get("completed_at")
        if completed_at and now - completed_at > _COMPLETED_TTL:
            expired.append(k)
            continue
        if v.get("session_id") == session_id:
            result[k] = v
    for k in expired:
        _running_sub_agents.pop(k, None)
    return result


async def spawn_sub_agent(
    agent_name: str,
    task: str,
    parent_context,
    include_history: bool = False,
    max_depth: int = 1,
    pipeline_run_id: int | None = None,
    pipeline_step_id: str | None = None,
) -> str:
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.loop import run_agent
    from crabagent.core.agent.tools.registry import ToolRegistry
    from crabagent.core.event import AgentEvent, EventType

    agent_def = await get_agent(agent_name)
    if not agent_def:
        return f"Error: agent '{agent_name}' not found"

    sub_registry = ToolRegistry()

    agent_tool_perms = agent_def.get("tool_permissions", {})
    current_depth = parent_context.metadata.get("_sub_agent_depth", 0)
    has_shared = False
    can_request_help = False

    for name, tool in parent_context.tool_registry._tools.items():
        if name in _DELEGATION_TOOLS:
            continue
        if name in _MEMORY_TOOLS:
            sub_registry._tools[name] = tool
            continue
        if agent_tool_perms.get(name) == "deny":
            continue
        sub_registry._tools[name] = tool

    has_shared = bool(_SHARED_TOOLS & set(sub_registry._tools.keys()))

    if agent_def.get("allow_delegation") and current_depth < max_depth:
        parent_tools = parent_context.tool_registry._tools
        if "request_help" in parent_tools:
            sub_registry._tools["request_help"] = parent_tools["request_help"]
            can_request_help = True

    sub_locale = parent_context.metadata.get("locale", parent_context.locale or "en")
    sub_context = AgentContext(
        workspace=parent_context.workspace,
        tool_registry=sub_registry,
        max_iterations=min(parent_context.max_iterations, 50),
        model=agent_def["model"] or parent_context.model,
        provider_name=parent_context.provider_name,
        system_prompt=_build_system_prompt(
            agent_def,
            has_shared=has_shared,
            can_request_help=can_request_help,
            locale=sub_locale,
        ),
    )

    sub_context.confirm_callback = None
    sub_context.tool_permissions = agent_tool_perms
    sub_context.metadata["_sub_agent_name"] = agent_name
    sub_context.metadata["_sub_agent_depth"] = current_depth + 1
    sub_context.locale = sub_locale
    sub_context.metadata["locale"] = sub_locale

    parent_user_id = parent_context.metadata.get("user_id", 0)
    if parent_user_id:
        sub_context.metadata["user_id"] = parent_user_id

    session_id = parent_context.metadata.get("session_id", "")
    if session_id:
        sub_context.metadata["session_id"] = session_id

    task_category = _classify_task(task)
    if parent_user_id:
        try:
            sub_context.system_prompt = await inject_agent_lessons(
                sub_context.system_prompt,
                user_id=parent_user_id,
                agent_name=agent_name,
                task_hint=task_category,
            )
        except Exception:
            logger.debug("Failed to inject lessons for sub-agent %s", agent_name, exc_info=True)

    shared_context = await _load_shared_context(session_id, locale=sub_locale)

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
        sub_context.messages = [{"role": "user", "content": "\n\n".join(prompt_parts)}]
    else:
        if shared_context:
            sub_context.messages = [{"role": "user", "content": f"{shared_context}\n\n## Your Task\n{task}"}]

    import uuid as _uuid

    sub_id = f"{agent_name}_{_uuid.uuid4().hex[:8]}"

    await parent_context.event_bus.emit(
        AgentEvent(
            type=EventType.SUB_AGENT_START,
            data={
                "sub_agent_id": sub_id,
                "agent_name": agent_name,
                "display_name": agent_def["display_name"],
                "task": task[:200],
                "model": agent_def.get("model") or parent_context.model,
                "session_id": session_id,
                "pipeline_run_id": pipeline_run_id,
                "pipeline_step_id": pipeline_step_id,
            },
        )
    )

    _running_sub_agents[sub_id] = {
        "session_id": session_id,
        "agent_name": agent_name,
        "display_name": agent_def["display_name"],
        "task": task[:200],
        "started_at": time.time(),
    }

    _last_text_flush = [0.0]
    _text_buffer = [""]
    _detail_lines: list[str] = []

    async def _bridge_events(event: AgentEvent):
        if event.type in (EventType.TEXT_DELTA,):
            _text_buffer[0] += event.data.get("text", "")
            now = time.time()
            if now - _last_text_flush[0] >= 0.3:
                _last_text_flush[0] = now
                await parent_context.event_bus.emit(
                    AgentEvent(
                        type=EventType.SUB_AGENT_TEXT_DELTA,
                        data={
                            "sub_agent_id": sub_id,
                            "agent_name": agent_name,
                            "text": _text_buffer[0],
                            "role": event.data.get("role", ""),
                        },
                    )
                )
                _text_buffer[0] = ""
        elif event.type in (EventType.TOOL_CALL,):
            tc_name = event.data.get("name", "")
            tc_args = _json.dumps(event.data.get("arguments", {}), ensure_ascii=False)
            _detail_lines.append(f"→ {tc_name}({tc_args[:120]})")
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_TOOL_CALL,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "name": tc_name,
                        "arguments": event.data.get("arguments", {}),
                        "id": event.data.get("id", ""),
                    },
                )
            )
        elif event.type in (EventType.TOOL_RESULT,):
            tr_name = event.data.get("name", "")
            tr_result = str(event.data.get("result", ""))
            _detail_lines.append(f"← {tr_name}: {tr_result[:200]}{'...' if len(tr_result) > 200 else ''}")
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_TOOL_RESULT,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "name": tr_name,
                        "result": tr_result[:500],
                    },
                )
            )
        elif event.type in (EventType.THINKING_DELTA,):
            _text_buffer[0] += event.data.get("text", "")
            now = time.time()
            if now - _last_text_flush[0] >= 0.3:
                _last_text_flush[0] = now
                await parent_context.event_bus.emit(
                    AgentEvent(
                        type=EventType.SUB_AGENT_TEXT_DELTA,
                        data={
                            "sub_agent_id": sub_id,
                            "agent_name": agent_name,
                            "text": _text_buffer[0],
                            "role": "thinking",
                        },
                    )
                )
                _text_buffer[0] = ""
        elif event.type in (EventType.THINKING_DONE,):
            pass
        elif event.type in (EventType.AGENT_ERROR,):
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_ERROR,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "error": event.data.get("error", "unknown error"),
                    },
                )
            )

    sub_context.event_bus.subscribe(_bridge_events)

    try:
        t0 = time.time()
        await run_agent(sub_context, task)
        elapsed = round(time.time() - t0, 1)

        if _text_buffer[0]:
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_TEXT_DELTA,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "text": _text_buffer[0],
                        "role": "",
                    },
                )
            )
            _text_buffer[0] = ""

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
                    "Failed to auto-save shared memory for %s",
                    agent_name,
                )

        if parent_user_id:
            try:
                from crabagent.core.database import agent_memory_upsert, task_record_create

                stats = {
                    "iterations": sub_context.iteration,
                    "max_iterations": sub_context.max_iterations,
                    "tokens": sub_context.total_tokens,
                    "elapsed": elapsed,
                }

                rule_lesson = _rule_extract_lesson(
                    agent_name=agent_name,
                    iterations=sub_context.iteration,
                    max_iterations=sub_context.max_iterations,
                    task=task,
                    result=last_text,
                    task_category=task_category,
                )
                if rule_lesson:
                    await agent_memory_upsert(
                        user_id=parent_user_id,
                        memory_type="agent_lesson",
                        agent_name=agent_name,
                        category=rule_lesson["category"],
                        key=rule_lesson["key"],
                        content=rule_lesson["content"],
                        importance=rule_lesson["importance"],
                        source_session=session_id,
                        source=rule_lesson["source"],
                        task_category=rule_lesson["task_category"],
                    )

                reflect_model = agent_def.get("model") or parent_context.model or ""
                reflect_provider = parent_context.provider_name
                if reflect_model:
                    llm_lesson = await _llm_reflect_lesson(
                        agent_name=agent_name,
                        task=task,
                        result=last_text,
                        task_category=task_category,
                        stats=stats,
                        model=reflect_model,
                        provider_name=reflect_provider,
                    )
                    if llm_lesson:
                        await agent_memory_upsert(
                            user_id=parent_user_id,
                            memory_type="agent_lesson",
                            agent_name=agent_name,
                            category=llm_lesson["category"],
                            key=llm_lesson["key"],
                            content=llm_lesson["content"],
                            importance=llm_lesson["importance"],
                            source_session=session_id,
                            source=llm_lesson["source"],
                            task_category=llm_lesson["task_category"],
                        )

                await task_record_create(
                    user_id=parent_user_id,
                    agent_name=agent_name,
                    task_summary=task[:200],
                    success=True,
                    elapsed=elapsed,
                    tokens=sub_context.total_tokens,
                    iterations=sub_context.iteration,
                )
            except Exception:
                logger.debug("Failed to extract lesson for %s", agent_name)

        await parent_context.event_bus.emit(
            AgentEvent(
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
            )
        )

        if sub_id in _running_sub_agents:
            _running_sub_agents[sub_id].update(
                {
                    "status": "done",
                    "elapsed": elapsed,
                    "tokens": sub_context.total_tokens,
                    "iterations": sub_context.iteration,
                }
            )

        detail_str = last_text
        if _detail_lines:
            detail_str = last_text + "\n" + "\n".join(_detail_lines)

        sub_content = _json.dumps(
            {
                "text": last_text,
                "detail": detail_str,
                "agent_name": agent_name,
                "display_name": agent_def["display_name"],
                "elapsed": elapsed,
                "tokens": sub_context.total_tokens,
                "iterations": sub_context.iteration,
            },
            ensure_ascii=False,
        )

        pending = parent_context.metadata.setdefault(
            "_pending_sub_agent_messages",
            [],
        )
        pending.append(
            {
                "role": "sub_agent",
                "content": sub_content,
                "name": agent_name,
            }
        )

        return last_text or "(sub-agent produced no output)"
    except Exception as e:
        logger.exception("Sub-agent %s failed", agent_name)
        error_elapsed = round(time.time() - t0, 1)

        if parent_context.metadata.get("user_id", 0):
            try:
                from crabagent.core.database import task_record_create

                await task_record_create(
                    user_id=parent_context.metadata["user_id"],
                    agent_name=agent_name,
                    task_summary=task[:200],
                    success=False,
                    elapsed=error_elapsed,
                )
            except Exception:
                pass

            try:
                from crabagent.core.database import agent_memory_upsert

                reflect_model = agent_def.get("model") or parent_context.model or ""
                reflect_provider = parent_context.provider_name
                error_stats = {
                    "iterations": sub_context.iteration,
                    "tokens": sub_context.total_tokens,
                    "elapsed": error_elapsed,
                }
                if reflect_model:
                    llm_lesson = await _llm_reflect_lesson(
                        agent_name=agent_name,
                        task=task,
                        result="",
                        task_category=task_category,
                        stats=error_stats,
                        model=reflect_model,
                        provider_name=reflect_provider,
                        error_msg=str(e),
                    )
                    if llm_lesson:
                        await agent_memory_upsert(
                            user_id=parent_user_id,
                            memory_type="agent_lesson",
                            agent_name=agent_name,
                            category=llm_lesson["category"],
                            key=llm_lesson["key"],
                            content=llm_lesson["content"],
                            importance=llm_lesson["importance"],
                            source_session=session_id,
                            source=llm_lesson["source"],
                            task_category=llm_lesson["task_category"],
                        )
            except Exception:
                pass
        await parent_context.event_bus.emit(
            AgentEvent(
                type=EventType.SUB_AGENT_ERROR,
                data={
                    "sub_agent_id": sub_id,
                    "agent_name": agent_name,
                    "error": str(e),
                },
            )
        )
        if sub_id in _running_sub_agents:
            _running_sub_agents[sub_id].update({"status": "error"})
        return f"Error: sub-agent '{agent_name}' failed: {e}"
    finally:
        if sub_id in _running_sub_agents:
            _running_sub_agents[sub_id]["completed_at"] = time.time()
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
