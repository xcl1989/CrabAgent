from __future__ import annotations

from crabagent.core.agent.tools.registry import registry

_MEMORY_TYPE_DESC = '"team" for project knowledge shared by all agents, "lesson" for behavioral patterns and experience'

_CATEGORY_DESC = (
    "team: tech_stack, architecture, convention, api, dependency, decision, user_preference. "
    "lesson: effective_strategy, failed_approach, user_preference, tool_tip"
)


def _active_agent(context) -> str:
    return context.metadata.get("_sub_agent_name") or getattr(context, "current_agent", "") or "default"


@registry.register(
    name="memory_save",
    description=(
        "Save a memory to long-term storage. Before saving, search existing memories and prefer "
        "updating the same relevant memory rather than creating a new key. Preserve useful old "
        "details and project/agent scope; do not merge merely similar but unrelated facts. "
        "Create a new memory only when no related entry exists. "
        "Use 'team' type for project knowledge all agents should know "
        "(tech stack, architecture, conventions, decisions). Only 'convention' and "
        "'decision' entries are loaded every turn; everything else is recalled when "
        "relevant, so keep topic-specific knowledge under architecture/api/feature. "
        "Use 'lesson' type for behavioral patterns "
        "(what works, what doesn't, user preferences). "
        "If the user makes a choice or rejects something, record it. "
        "Memories persist across sessions; relevant entries may be recalled automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_type": {
                "type": "string",
                "enum": ["team", "lesson"],
                "description": _MEMORY_TYPE_DESC,
            },
            "category": {
                "type": "string",
                "description": _CATEGORY_DESC,
            },
            "key": {
                "type": "string",
                "description": (
                    "Unique identifier naming the SUBJECT, not the episode: "
                    "'tech_stack:framework', 'convention:release-pipeline-pypi', "
                    "'decision:nonexclusive-collaboration', "
                    "'user_pref:verify-build-before-install', "
                    "'lesson:coder:restart-backend-after-edit'. "
                    "Use lowercase kebab-case and never a hash, timestamp or counter."
                ),
            },
            "content": {
                "type": "string",
                "description": "The memory content. Be specific and actionable.",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Optional one-line digest (<=120 chars) used when this memory is "
                    "injected on every turn. Required for long 'convention'/'decision' "
                    "entries so the full text stays available on demand."
                ),
            },
            "importance": {
                "type": "number",
                "description": "0.0-1.0. Higher = more important. Default 0.5.",
            },
            "confidence": {
                "type": "number",
                "description": "0.0-1.0. How certain is this memory. Default 1.0.",
            },
        },
        "required": ["memory_type", "category", "key", "content"],
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_save(
    memory_type: str,
    category: str,
    key: str,
    content: str,
    importance: float = 0.5,
    confidence: float = 1.0,
    summary: str = "",
    context=None,
) -> str:
    if context is None:
        return "Error: memory_save requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    if len(content) > 3000:
        content = content[:3000]
    importance = max(0.0, min(1.0, importance))
    confidence = max(0.0, min(1.0, confidence))
    agent_name = context.metadata.get("_sub_agent_name", "")
    if memory_type == "lesson" and not agent_name:
        agent_name = _active_agent(context)
    session_id = context.metadata.get("session_id", "")
    from crabagent.core.database import agent_memory_upsert

    workspace_path = context.metadata.get("workspace_path") or str(getattr(context, "workspace", "") or "")
    default_scope = ("workspace" if workspace_path else "global") if memory_type == "team" else "agent"
    # Every memory is recalled on relevance only. What must be known on
    # *every* turn belongs in the workspace AGENTS.md, not in the memory store.
    # Scope still decides *visibility* (which workspace may see the entry).
    await agent_memory_upsert(
        user_id=user_id,
        memory_type=memory_type,
        agent_name=agent_name,
        category=category,
        key=key,
        content=content,
        importance=importance,
        confidence=confidence,
        source_session=session_id,
        source="",
        task_category="",
        scope=default_scope,
        workspace_path="" if default_scope == "global" else workspace_path,
        recall_policy="query_only",
        summary=(summary or "").strip()[:200],
    )
    return f"Memory saved: [{memory_type}] {key}"


@registry.register(
    name="memory_recall",
    description=(
        "Search long-term memory by keyword. "
        "Returns matching memories sorted by importance. "
        "Use this to recall project knowledge or past lessons."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to find in memory keys or content",
            },
            "memory_type": {
                "type": "string",
                "description": "Filter by type: 'team' or 'lesson'. Empty for all.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return. Default 5.",
            },
        },
        "required": ["query"],
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_recall(
    query: str,
    memory_type: str = "",
    limit: int = 5,
    context=None,
) -> str:
    if context is None:
        return "Error: memory_recall requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_search_vector

    results = await agent_memory_search_vector(
        user_id,
        query,
        memory_type=memory_type,
        limit=limit,
        fallback=True,
        visible_only=True,
        workspace_path=context.metadata.get("workspace_path") or str(getattr(context, "workspace", "") or ""),
        agent_name=_active_agent(context),
    )
    if not results:
        return f"No memories found for '{query}'."
    lines = [f"# Memory Search: '{query}' ({len(results)} found)\n"]
    for r in results:
        type_tag = r["memory_type"]
        agent_tag = f" [{r['agent_name']}]" if r["agent_name"] else ""
        sim_tag = f", similarity={r['_similarity']:.2f}" if "_similarity" in r else ""
        lines.append(
            f"- **{r['key']}** (id={r.get('id', '?')}, {type_tag}{agent_tag}, "
            f"importance={r['importance']:.1f}{sim_tag}): {r['content']}"
        )
    return "\n".join(lines)


@registry.register(
    name="memory_replace",
    description=(
        "Replace part of an existing memory's content. "
        "Use this to update or correct a specific part of a memory without rewriting the whole thing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The memory key to update",
            },
            "memory_id": {"type": "integer", "description": "Memory ID to disambiguate matching keys"},
            "old_text": {
                "type": "string",
                "description": "The exact text to find and replace",
            },
            "new_text": {
                "type": "string",
                "description": "The replacement text",
            },
        },
        "required": ["key", "old_text", "new_text"],
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_replace(key: str, old_text: str, new_text: str, context=None, memory_id: int | None = None) -> str:
    if context is None:
        return "Error: memory_replace requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_replace as _replace

    ok = await _replace(
        user_id,
        key,
        old_text,
        new_text,
        memory_id=memory_id,
        visible_only=True,
        workspace_path=context.metadata.get("workspace_path") or str(getattr(context, "workspace", "") or ""),
        agent_name=_active_agent(context),
    )
    if ok:
        return f"Memory updated: {key}"
    return f"Error: memory '{key}' not found, ambiguous, or old_text not matched"


@registry.register(
    name="memory_list",
    description="List all memories, optionally filtered by type or category.",
    parameters={
        "type": "object",
        "properties": {
            "memory_type": {
                "type": "string",
                "description": "Filter: 'team' or 'lesson'. Empty for all.",
            },
            "category": {
                "type": "string",
                "description": "Filter by category. Empty for all.",
            },
        },
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_list(memory_type: str = "", category: str = "", context=None) -> str:
    if context is None:
        return "Error: memory_list requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_list_all

    items = await agent_memory_list_all(
        user_id,
        memory_type=memory_type,
        category=category,
        visible_only=True,
        workspace_path=context.metadata.get("workspace_path") or str(getattr(context, "workspace", "") or ""),
        agent_name=_active_agent(context),
    )
    if not items:
        return "No memories stored yet."
    lines = [f"# Memories ({len(items)} total)\n"]
    for item in items:
        agent_tag = f" [{item['agent_name']}]" if item["agent_name"] else ""
        preview = item["content"]
        if len(preview) > 120:
            preview = preview[:120] + "..."
        lines.append(
            f"- **{item['key']}** (id={item.get('id', '?')}, {item['memory_type']}{agent_tag}, "
            f"imp={item['importance']:.1f}): {preview}"
        )
    return "\n".join(lines)


@registry.register(
    name="memory_forget",
    description="Delete a specific memory by key.",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The memory key to delete",
            },
            "memory_id": {"type": "integer", "description": "Memory ID to disambiguate matching keys"},
        },
        "required": ["key"],
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_forget(key: str, context=None, memory_id: int | None = None) -> str:
    if context is None:
        return "Error: memory_forget requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_delete

    ok = await agent_memory_delete(
        user_id,
        key,
        memory_id=memory_id,
        visible_only=True,
        workspace_path=context.metadata.get("workspace_path") or str(getattr(context, "workspace", "") or ""),
        agent_name=_active_agent(context),
    )
    if ok:
        return f"Memory deleted: {key}"
    return f"Error: memory '{key}' not found or ambiguous; specify memory_id"
