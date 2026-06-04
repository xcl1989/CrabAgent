from pathlib import Path

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
                "description": "Absolute file system path to the file to create or overwrite.",
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
def write_file(file_path: str, content: str) -> str:
    if not file_path or not file_path.strip():
        return "Error: file_path is required and must be a non-empty absolute path"
    if not content:
        return "Error: content is required and must be a non-empty string"

    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"
