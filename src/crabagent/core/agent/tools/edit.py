from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="edit",
    description="Perform exact string replacement in a file. The old_string must match exactly.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to find and replace.",
            },
            "new_string": {
                "type": "string",
                "description": "Text to replace it with.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    requires_permission=True,
)
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return f"Error: file does not exist: {file_path}"

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Count occurrences first (safe — returns 0 instead of raising)
    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1:
        return f"Error: old_string found {count} times in {file_path}. Provide more context to make it unique."

    # Now safe to compute line number
    index = content.index(old_string)
    line_num = content[:index].count("\n") + 1

    new_content = content.replace(old_string, new_string, 1)
    path.write_text(new_content, encoding="utf-8")
    return f"Successfully replaced 1 occurrence in {file_path} @ L{line_num}"
