from crabagent.core.agent.tools.path_utils import resolve_tool_path
from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="write",
    description=(
        "Write content to a file. Creates parent directories if needed. "
        "Overwrites existing files. Both file_path and content are required "
        "and must be non-empty."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute file system path or workspace-relative path to the file to create or overwrite.",
            },
            "content": {
                "type": "string",
                "description": "The full text content to write to the file. Must be a non-empty string.",
            },
        },
        "required": ["file_path", "content"],
    },
    requires_permission=True,
)
def write_file(file_path: str, content: str, context=None) -> str:
    if not file_path or not file_path.strip():
        return "Error: file_path is required and must be a non-empty path"
    if not content:
        return "Error: content is required and must be a non-empty string"

    path, error = resolve_tool_path(file_path, context)
    if error:
        return error
    assert path is not None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


@registry.register(
    name="update_agents_md",
    description=(
        "Update the project's AGENTS.md file — the workspace-level rules file "
        "that is automatically loaded into every session's system prompt. "
        "Use this to persist project conventions, build commands, architecture notes, "
        "or any context that should be available in future sessions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full Markdown content for AGENTS.md.",
            },
        },
        "required": ["content"],
    },
    requires_permission=True,
    metadata={"source": "builtin", "category": "file_management"},
)
def update_agents_md(content: str, context=None) -> str:
    if not content or not content.strip():
        return "Error: content must be a non-empty string"
    if context is None:
        return "Error: update_agents_md requires an active session"

    from crabagent.core.project_memory import save_agents_md

    locale = context.metadata.get("locale", context.locale or "en")
    return save_agents_md(context.workspace, content, locale=locale)
