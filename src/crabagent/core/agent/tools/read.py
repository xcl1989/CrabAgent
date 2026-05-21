from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="read",
    description=(
        "Read a file or directory from the filesystem. Returns file contents with line numbers, or directory listing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file or directory to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Default: 1.",
                "default": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Default: 2000.",
                "default": 2000,
            },
        },
        "required": ["file_path"],
    },
)
def read_file(file_path: str, offset: int = 1, limit: int = 2000) -> str:
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return f"Error: path does not exist: {file_path}"

    if path.is_dir():
        entries = []
        for entry in sorted(path.iterdir()):
            suffix = "/" if entry.is_dir() else ""
            entries.append(entry.name + suffix)
        return "\n".join(entries)

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except Exception as e:
        return f"Error reading file: {e}"

    total = len(lines)
    start = max(0, offset - 1)
    end = min(total, start + limit)
    selected = lines[start:end]

    result = []
    for i, line in enumerate(selected, start=start + 1):
        result.append(f"{i}: {line.rstrip()}")

    header = f"[File: {file_path} ({total} lines total)]\n"
    return header + "\n".join(result)
