from __future__ import annotations

from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="shared_put",
    description=(
        "Save an important finding or note to the shared team workspace. "
        "Other agents in the same session can read it with shared_get. "
        "Use this to pass knowledge between team members."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": (
                    "A descriptive key for this note, "
                    "e.g. 'research_findings', 'api_endpoints', 'decisions'"
                ),
            },
            "value": {
                "type": "string",
                "description": "The content to save. Keep it concise and well-structured.",
            },
        },
        "required": ["key", "value"],
    },
    metadata={"source": "builtin", "category": "shared"},
)
async def shared_put(key: str, value: str, context=None) -> str:
    if context is None:
        return "Error: shared_put requires an active session"
    session_id = context.metadata.get("session_id", "")
    if not session_id:
        return "Error: no active session for shared workspace"
    if len(value) > 10000:
        value = value[:10000]
    author = context.metadata.get("_sub_agent_name", "main")
    from crabagent.core.database import shared_memory_put as _put
    await _put(session_id, key, value, author)
    return f"Saved to shared workspace: {key}"


@registry.register(
    name="shared_get",
    description=(
        "Read a note from the shared team workspace. "
        "Returns the value saved by any team member for the given key."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The key to look up in the shared workspace",
            },
        },
        "required": ["key"],
    },
    metadata={"source": "builtin", "category": "shared"},
)
async def shared_get(key: str, context=None) -> str:
    if context is None:
        return "Error: shared_get requires an active session"
    session_id = context.metadata.get("session_id", "")
    if not session_id:
        return "Error: no active session for shared workspace"
    from crabagent.core.database import shared_memory_get as _get
    value = await _get(session_id, key)
    if value is None:
        return f"(not found: {key})"
    return value


@registry.register(
    name="shared_list",
    description=(
        "List all notes in the shared team workspace. "
        "Shows keys, authors, and a preview of each note."
    ),
    parameters={
        "type": "object",
        "properties": {},
    },
    metadata={"source": "builtin", "category": "shared"},
)
async def shared_list(context=None) -> str:
    if context is None:
        return "Error: shared_list requires an active session"
    session_id = context.metadata.get("session_id", "")
    if not session_id:
        return "Error: no active session for shared workspace"
    from crabagent.core.database import shared_memory_get_all as _get_all
    items = await _get_all(session_id)
    if not items:
        return "Shared workspace is empty."
    lines = [f"# Shared Workspace ({len(items)} notes)\n"]
    for item in items:
        preview = item["value"][:120]
        if len(item["value"]) > 120:
            preview += "..."
        author_tag = f" (by {item['author']})" if item["author"] else ""
        lines.append(f"- **{item['key']}**{author_tag}: {preview}")
    return "\n".join(lines)
