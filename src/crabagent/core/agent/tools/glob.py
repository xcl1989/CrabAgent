from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="glob",
    description="Find files matching a glob pattern. Returns sorted file paths.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": 'Glob pattern (e.g. "**/*.py", "src/**/*.tsx").',
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Default: current directory.",
            },
        },
        "required": ["pattern"],
    },
)
def glob_files(pattern: str, path: str = ".") -> str:
    from pathlib import Path

    root = Path(path)
    if not root.exists():
        return f"Error: path does not exist: {path}"

    matches = sorted(root.glob(pattern))
    if not matches:
        return "No files found matching pattern."

    lines = []
    for m in matches:
        rel = m.relative_to(root) if m.is_relative_to(root) else m
        lines.append(str(rel))
    return "\n".join(lines)
