from __future__ import annotations

from crabagent.core.agent.tools.registry import registry

_MEMORY_TYPE_DESC = (
    '"team" for project knowledge shared by all agents, '
    '"lesson" for behavioral patterns and experience'
)

_CATEGORY_DESC = (
    "team: tech_stack, architecture, convention, api, dependency, decision, user_preference. "
    "lesson: effective_strategy, failed_approach, user_preference, tool_tip"
)


@registry.register(
    name="memory_save",
    description=(
        "Save a memory to long-term storage. "
        "Use 'team' type for project knowledge all agents should know "
        "(tech stack, architecture, conventions, decisions). "
        "Use 'lesson' type for behavioral patterns "
        "(what works, what doesn't, user preferences). "
        "If the user makes a choice or rejects something, record it. "
        "Memories persist across sessions and are automatically loaded on startup."
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
                    "Unique identifier, e.g. "
                    "'tech_stack:framework', 'user_preference:language', "
                    "'lesson:coder:efficiency'"
                ),
            },
            "content": {
                "type": "string",
                "description": "The memory content. Be specific and actionable.",
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
    session_id = context.metadata.get("session_id", "")
    from crabagent.core.database import agent_memory_upsert
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
    from crabagent.core.database import agent_memory_search
    results = await agent_memory_search(user_id, query, memory_type=memory_type, limit=limit)
    if not results:
        return f"No memories found for '{query}'."
    lines = [f"# Memory Search: '{query}' ({len(results)} found)\n"]
    for r in results:
        type_tag = r["memory_type"]
        agent_tag = f" [{r['agent_name']}]" if r["agent_name"] else ""
        lines.append(
            f"- **{r['key']}** ({type_tag}{agent_tag}, "
            f"importance={r['importance']:.1f}): {r['content']}"
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
async def memory_replace(key: str, old_text: str, new_text: str, context=None) -> str:
    if context is None:
        return "Error: memory_replace requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_replace as _replace
    ok = await _replace(user_id, key, old_text, new_text)
    if ok:
        return f"Memory updated: {key}"
    return f"Error: memory '{key}' not found or old_text not matched"


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
    items = await agent_memory_list_all(user_id, memory_type=memory_type, category=category)
    if not items:
        return "No memories stored yet."
    lines = [f"# Memories ({len(items)} total)\n"]
    for item in items:
        agent_tag = f" [{item['agent_name']}]" if item["agent_name"] else ""
        preview = item["content"]
        if len(preview) > 120:
            preview = preview[:120] + "..."
        lines.append(
            f"- **{item['key']}** ({item['memory_type']}{agent_tag}, "
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
        },
        "required": ["key"],
    },
    metadata={"source": "builtin", "category": "memory"},
)
async def memory_forget(key: str, context=None) -> str:
    if context is None:
        return "Error: memory_forget requires an active session"
    user_id = context.metadata.get("user_id", 0)
    if not user_id:
        return "Error: no user_id in context"
    from crabagent.core.database import agent_memory_delete
    ok = await agent_memory_delete(user_id, key)
    if ok:
        return f"Memory deleted: {key}"
    return f"Error: memory '{key}' not found"
