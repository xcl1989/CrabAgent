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
        lines.append(f"- **{a['display_name']}** (`{a['name']}`): {a['role']}. {a['goal']}{tools_info}")
    lines.extend(
        [
            "",
            "### Delegation Tools",
            "",
            "- `list_agents`: List all available agents with details",
            "- `plan_task(task)`: Analyze a complex task and produce an execution plan (does not execute)",
            "- `delegate_task(agent_name, task)`: Delegate a task to a specific agent",
            "- `delegate_parallel(tasks)`: Run multiple independent agent tasks simultaneously (no ordering)",
            "- `handoff_to(agent_name, summary)`: Hand off work to another agent with context",
            "- `run_pipeline(steps)`: Multi-step workflow with dependencies. "
            "Steps without depends_on run in parallel. Prefer for complex workflows.",
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
            "- Multiple independent subtasks (no ordering needed) -> `delegate_parallel`",
            "- Multi-step workflow with ordering or data flow (e.g., research -> analyze -> write) -> `run_pipeline`",
            "- User asks for multiple sub-agents or parallel execution -> "
            "use `delegate_parallel` or `run_pipeline`, not sequential `delegate_task`",
            "",
        ]
    )
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


def _classify_task(task: str) -> str:
    tl = task.lower()
    code_kw = [
        "code",
        "代码",
        "bug",
        "debug",
        "refactor",
        "重构",
        "implement",
        "实现",
        "function",
        "函数",
        "class",
        "api",
        "test",
        "测试",
        "write",
        "编写",
        "fix",
        "修复",
    ]
    research_kw = [
        "search",
        "搜索",
        "research",
        "调研",
        "find",
        "查找",
        "browse",
        "浏览",
        "scrape",
        "爬取",
        "look up",
        "查询",
    ]
    analysis_kw = [
        "analyze",
        "分析",
        "compare",
        "比较",
        "report",
        "报告",
        "review",
        "审查",
        "evaluate",
        "评估",
        "check",
        "检查",
    ]
    writing_kw = [
        "translate",
        "翻译",
        "edit",
        "编辑",
        "format",
        "格式化",
        "document",
        "文档",
        "content",
        "内容",
        "article",
        "文章",
        "write",
        "撰写",
    ]
    scores = {"code": 0, "research": 0, "analysis": 0, "writing": 0}
    for kw in code_kw:
        if kw in tl:
            scores["code"] += 1
    for kw in research_kw:
        if kw in tl:
            scores["research"] += 1
    for kw in analysis_kw:
        if kw in tl:
            scores["analysis"] += 1
    for kw in writing_kw:
        if kw in tl:
            scores["writing"] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def _rule_extract_lesson(
    agent_name: str,
    iterations: int,
    max_iterations: int,
    task: str,
    result: str,
    task_category: str = "general",
) -> dict | None:
    if iterations >= max_iterations * 0.8 and result:
        return {
            "category": "failed_approach",
            "key": f"lesson:{agent_name}:rule:high_iterations:{int(time.time())}",
            "content": (
                f"Exhausted {iterations}/{max_iterations} iterations on: {task[:100]}. "
                f"Next time: decompose complex tasks, narrow scope, or use fewer tools per iteration."
            ),
            "importance": 0.5,
            "source": "rule",
            "task_category": task_category,
        }
    return None


async def _llm_reflect_lesson(
    agent_name: str,
    task: str,
    result: str,
    task_category: str,
    stats: dict,
    model: str,
    provider_name: str | None = None,
    error_msg: str = "",
) -> dict | None:
    try:
        _t = time.time()
        import litellm

        from crabagent.core.provider_store import get_default_provider, get_provider

        if error_msg:
            result_text = f"(TASK FAILED) Error: {error_msg[:600]}"
        else:
            result_text = result[:800] if result else "(no output)"

        prompt = (
            f"Based on this completed task, extract ONE concrete lesson.\n\n"
            f"Agent: {agent_name}\n"
            f"Task: {task[:400]}\n"
            f"Output: {result_text}\n"
            f"Stats: {stats['iterations']} steps, {stats['tokens']} tokens, {stats['elapsed']}s\n\n"
            f"Identify one specific tip, pitfall, or technique that would help in future similar tasks. "
            f"Be specific and actionable. Do not give generic praise.\n\n"
            f"Category (pick one): {task_category}\n\n"
            f"If there is truly nothing worth noting, respond with just the word: NONE\n"
            f"Otherwise respond with:\n"
            f"Category: {{category}}\n"
            f"Insight: {{one sentence of actionable advice}}"
        )

        if provider_name:
            provider = await get_provider(provider_name)
        else:
            provider = await get_default_provider()
        if not provider:
            logger.warning("LLM reflection skipped for %s: no provider found", agent_name)
            return None

        logger.info(
            "_llm_reflect_lesson for %s: model=%s provider=%s task_cat=%s error=%s",
            agent_name,
            model,
            provider.name,
            task_category,
            bool(error_msg),
        )

        llm_params = {"api_key": provider.api_key}
        if provider.base_url:
            llm_params["api_base"] = provider.base_url
            llm_params["custom_llm_provider"] = "openai"

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
            **llm_params,
        )

        _elapsed = time.time() - _t
        if _elapsed > 5:
            logger.debug("_llm_reflect_lesson for %s took %.1fs", agent_name, _elapsed)

        text = ""
        if response.choices:
            msg = response.choices[0].message
            text = (msg.content or "").strip()
            if not text:
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    text = reasoning.strip()
                    if "<｜end▁of▁thinking｜>" in text:
                        text = text.rsplit(" response", 1)[-1].strip()

        if text.strip().upper() in ("NONE", "SKIP"):
            logger.debug("_llm_reflect_lesson for %s: nothing to learn", agent_name)
            return None

        category = task_category
        insight = ""
        for line in text.split("\n"):
            line = line.strip()
            if line.lower().startswith("category:") or line.startswith("类别:"):
                cat = line.split(":", 1)[1].strip().lower()
                if cat in {"code", "research", "analysis", "writing", "general"}:
                    category = cat
            elif line.lower().startswith("insight:") or line.startswith("经验:") or line.startswith("反思:"):
                insight = line.split(":", 1)[1].strip()

        if not insight:
            insight = text[:250]

        bad_words = [
            "completed efficiently",
            "completed in",
            "did a good",
            "well done",
            "great job",
            "successfully completed",
            "完成任务",
            "完成得很好",
            "做得很好",
            "顺利完成",
            "completed the task",
        ]
        tl = insight.lower()
        if any(bw in tl for bw in bad_words):
            logger.debug("_llm_reflect_lesson for %s: insight too generic, skipping", agent_name)
            return None

        if len(insight) < 10:
            logger.warning(
                "_llm_reflect_lesson for %s: insight too short (%d chars): %s",
                agent_name,
                len(insight),
                text[:100],
            )
            return None

        return {
            "category": "failed_approach" if error_msg else "effective_strategy",
            "key": f"lesson:{agent_name}:llm:{int(time.time())}",
            "content": insight,
            "importance": 0.8 if error_msg else 0.7,
            "source": "llm",
            "task_category": category,
        }
    except Exception:
        logger.warning("LLM reflection failed for %s", agent_name, exc_info=True)
        return None


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
            agent_def,
            has_shared=has_shared,
            can_request_help=can_request_help,
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
    task_category = _classify_task(task)
    if parent_user_id:
        try:
            from crabagent.core.database import agent_memory_get_by_agent, agent_memory_search

            agent_lessons = await agent_memory_get_by_agent(parent_user_id, agent_name, limit=5)
            try:
                similar = await agent_memory_search(
                    parent_user_id,
                    task_category,
                    memory_type="agent_lesson",
                    limit=3,
                )
                existing_keys = {item["key"] for item in agent_lessons}
                for s in similar:
                    if s["key"] not in existing_keys and s["agent_name"] == agent_name:
                        agent_lessons.append(s)
            except Exception:
                pass
        except Exception:
            pass

    if agent_lessons:
        lesson_by_cat: dict[str, list[str]] = {}
        for lesson in agent_lessons:
            cat = lesson.get("category", "effective_strategy")
            source = lesson.get("source", "")
            tag = "⚠️" if cat == "failed_approach" else "🧠" if source == "llm" else "📋"
            lesson_by_cat.setdefault(cat, []).append(f"{tag} {lesson['content']}")

        lesson_lines = ["\n\n## Your Past Experiences\n"]
        lesson_lines.append("Use these to guide your approach. Avoid repeating past mistakes.\n")
        if "failed_approach" in lesson_by_cat:
            lesson_lines.append("### Pitfalls to Avoid")
            for l in lesson_by_cat["failed_approach"]:
                lesson_lines.append(f"- {l}")
            lesson_lines.append("")
        if "effective_strategy" in lesson_by_cat:
            lesson_lines.append("### What Worked Before")
            for l in lesson_by_cat["effective_strategy"]:
                lesson_lines.append(f"- {l}")
            lesson_lines.append("")
        sub_context.system_prompt += "\n".join(lesson_lines)

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
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_TOOL_CALL,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "name": event.data.get("name", ""),
                        "arguments": event.data.get("arguments", {}),
                        "id": event.data.get("id", ""),
                    },
                )
            )
        elif event.type in (EventType.TOOL_RESULT,):
            await parent_context.event_bus.emit(
                AgentEvent(
                    type=EventType.SUB_AGENT_TOOL_RESULT,
                    data={
                        "sub_agent_id": sub_id,
                        "agent_name": agent_name,
                        "name": event.data.get("name", ""),
                        "result": event.data.get("result", "")[:500],
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

        sub_content = _json.dumps(
            {
                "text": last_text,
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
