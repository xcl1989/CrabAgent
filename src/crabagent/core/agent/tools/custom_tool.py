from __future__ import annotations

import json
import re

from crabagent.core.agent.tools.registry import registry

_TOOL_DIR_NAME = ".crabagent/tools"
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _tool_dir(context) -> tuple:
    ws = context.workspace
    td = ws / _TOOL_DIR_NAME
    return td


def _generate_tool_file(name: str, description: str, parameters: dict | None, code: str) -> str:
    params_str = json.dumps(parameters or {"type": "object", "properties": {}}, ensure_ascii=False)
    return (
        f'name = "{name}"\n'
        f'description = """{description}"""\n'
        f"parameters = {params_str}\n"
        f"requires_permission = True\n"
        f"\n"
        f"{code}\n"
    )


def _validate_code(code: str, name: str) -> str | None:
    try:
        compile(code, "<tool-code>", "exec")
    except SyntaxError as e:
        return f"Syntax error in code: {e}"
    ns: dict = {}
    try:
        exec(code, ns)
    except Exception as e:
        return f"Error executing code: {e}"
    if "run" not in ns or not callable(ns["run"]):
        return "Code must define a 'run' function"
    return None


@registry.register(
    name="create_tool",
    description=(
        "Create a reusable custom tool. "
        "The tool is saved to disk and registered immediately — "
        "it will be available in this session and all future sessions. "
        "Provide a complete 'run' function definition. "
        "The function parameters should match your parameter schema "
        "and it must return a string. "
        "Example code: "
        "'def run(text: str, key: str) -> str:\\n"
        "    import json\\n"
        "    data = json.loads(text)\\n"
        '    return str(data.get(key, "not found"))\''
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tool name in snake_case (e.g. 'parse_csv', 'fetch_weather')",
            },
            "description": {
                "type": "string",
                "description": "What the tool does, used as the tool description for the LLM",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "JSON Schema for input parameters. "
                    "Example: {'type':'object','properties':{'text':{'type':'string'}},'required':['text']}"
                ),
            },
            "code": {
                "type": "string",
                "description": (
                    "Python code containing a 'def run(...)' function. "
                    "Parameters match your JSON schema. Must return a string. "
                    "Can import standard library modules."
                ),
            },
        },
        "required": ["name", "description", "code"],
    },
    requires_permission=True,
    metadata={"source": "builtin", "category": "tool_management"},
)
async def create_tool(
    name: str,
    description: str,
    code: str,
    parameters: dict | None = None,
    context=None,
) -> str:
    if context is None:
        return "Error: create_tool requires an active session"

    if not _NAME_RE.match(name):
        return (
            f"Error: tool name '{name}' must be snake_case "
            f"(lowercase letters, digits, underscores, starting with a letter)"
        )

    if len(name) > 64:
        return "Error: tool name too long (max 64 characters)"

    if name in (
        "bash",
        "read",
        "write",
        "edit",
        "glob",
        "grep",
        "web_search",
        "web_scrape",
        "memory_save",
        "memory_recall",
        "memory_replace",
        "memory_list",
        "memory_forget",
        "shared_put",
        "shared_get",
        "shared_list",
        "create_tool",
        "update_tool",
        "delete_tool",
        "delegate_task",
        "delegate_parallel",
        "run_pipeline",
        "plan_task",
        "handoff_to",
        "request_help",
        "list_agents",
        "skill",
        "update_agents_md",
    ):
        return f"Error: '{name}' is a reserved built-in tool name"

    err = _validate_code(code, name)
    if err:
        return f"Error: {err}"

    td = _tool_dir(context)
    tool_file = td / f"{name}.py"

    if tool_file.exists():
        return f"Error: tool '{name}' already exists. Use update_tool to modify it, or delete_tool to remove it first."

    file_content = _generate_tool_file(name, description, parameters, code)

    td.mkdir(parents=True, exist_ok=True)
    tool_file.write_text(file_content, encoding="utf-8")

    from crabagent.core.tool_loader import _load_tool_file

    _load_tool_file(tool_file, context.tool_registry)

    registered = context.tool_registry.get(name)
    if not registered:
        tool_file.unlink(missing_ok=True)
        return f"Error: tool '{name}' was saved but failed to register. Check the code for import errors."

    try:
        user_id = context.metadata.get("user_id", 0)
        if user_id:
            from crabagent.core.database import agent_memory_upsert

            session_id = context.metadata.get("session_id", "")
            await agent_memory_upsert(
                user_id=user_id,
                memory_type="lesson",
                agent_name="",
                category="tool_tip",
                key=f"tool:{name}",
                content=(
                    f"Created custom tool '{name}': {description}. "
                    f"This tool is available for future tasks. "
                    f"Use it when you need to {description.lower()}."
                ),
                importance=0.7,
                confidence=1.0,
                source_session=session_id,
                source="auto",
                task_category="",
                scope="workspace",
                workspace_path=str(getattr(context, 'workspace', '') or ''),
                recall_policy="query_only",
            )
    except Exception:
        pass

    return (
        f"Tool '{name}' created successfully.\n"
        f"  File: {tool_file}\n"
        f"  Description: {description}\n"
        f"  Parameters: {json.dumps(parameters or {})}\n"
        f"  The tool is now available in this session and will auto-load in future sessions.\n"
        f"  A lesson has been saved so you remember this tool exists."
    )


@registry.register(
    name="update_tool",
    description=("Update an existing custom tool's code. The tool file is overwritten and re-registered immediately."),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the tool to update",
            },
            "code": {
                "type": "string",
                "description": "New Python code containing a complete 'def run(...)' function",
            },
            "description": {
                "type": "string",
                "description": "Optional: new description for the tool",
            },
            "parameters": {
                "type": "object",
                "description": "Optional: new JSON Schema for parameters",
            },
        },
        "required": ["name", "code"],
    },
    requires_permission=True,
    metadata={"source": "builtin", "category": "tool_management"},
)
async def update_tool(
    name: str,
    code: str,
    description: str | None = None,
    parameters: dict | None = None,
    context=None,
) -> str:
    if context is None:
        return "Error: update_tool requires an active session"

    td = _tool_dir(context)
    tool_file = td / f"{name}.py"

    if not tool_file.exists():
        return f"Error: tool '{name}' does not exist. Use create_tool to create it first."

    existing = tool_file.read_text(encoding="utf-8")
    existing_ns: dict = {}
    try:
        exec(existing, existing_ns)
    except Exception:
        pass

    new_desc = description or existing_ns.get("description", f"Custom tool {name}")
    new_params = parameters or existing_ns.get("parameters", None)

    err = _validate_code(code, name)
    if err:
        return f"Error: {err}"

    file_content = _generate_tool_file(name, new_desc, new_params, code)
    tool_file.write_text(file_content, encoding="utf-8")

    if name in context.tool_registry._tools:
        del context.tool_registry._tools[name]

    from crabagent.core.tool_loader import _load_tool_file

    _load_tool_file(tool_file, context.tool_registry)

    registered = context.tool_registry.get(name)
    if not registered:
        return f"Warning: tool '{name}' file was updated but failed to re-register. The old tool may still be active."

    return f"Tool '{name}' updated successfully.\n  File: {tool_file}\n  The updated tool is now active."


@registry.register(
    name="delete_tool",
    description="Delete a custom tool. Removes the tool file and unregisters it from the current session.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the tool to delete",
            },
        },
        "required": ["name"],
    },
    requires_permission=True,
    metadata={"source": "builtin", "category": "tool_management"},
)
async def delete_tool(name: str, context=None) -> str:
    if context is None:
        return "Error: delete_tool requires an active session"

    td = _tool_dir(context)
    tool_file = td / f"{name}.py"

    if not tool_file.exists():
        return f"Error: tool '{name}' does not exist."

    tool_info = context.tool_registry.get(name)
    if tool_info and tool_info.metadata and tool_info.metadata.get("source") == "builtin":
        return f"Error: '{name}' is a built-in tool and cannot be deleted."

    tool_file.unlink()

    if name in context.tool_registry._tools:
        del context.tool_registry._tools[name]

    try:
        user_id = context.metadata.get("user_id", 0)
        if user_id:
            from crabagent.core.database import agent_memory_delete

            await agent_memory_delete(user_id, f"tool:{name}")
    except Exception:
        pass

    return f"Tool '{name}' deleted successfully."
