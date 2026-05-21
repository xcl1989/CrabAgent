from pathlib import Path

from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="write",
    description="Write content to a file. Creates parent directories if needed. Overwrites existing files.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to write to.",
            },
            "content": {
                "type": "string",
                "description": "Content to write.",
            },
        },
        "required": ["file_path", "content"],
    },
    requires_permission=True,
)
def write_file(file_path: str, content: str) -> str:
    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"
