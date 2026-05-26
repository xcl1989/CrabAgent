from crabagent.core.agent.tools.registry import registry

_GLOB_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    ".eggs",
    "dist",
    "build",
    ".opencode",
    ".crabagent",
}

_GLOB_MAX_RESULTS = 500


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

    root = Path(path).resolve()
    if not root.exists():
        return f"Error: path does not exist: {path}"

    matches = sorted(root.glob(pattern))
    if not matches:
        return "No files found matching pattern."

    lines = []
    for m in matches:
        parts = set(m.relative_to(root).parts) if m.is_relative_to(root) else set(m.parts)
        if parts & _GLOB_EXCLUDE_DIRS:
            continue
        rel = m.relative_to(root) if m.is_relative_to(root) else m
        lines.append(str(rel))
        if len(lines) >= _GLOB_MAX_RESULTS:
            lines.append(f"\n... [truncated: {len(matches) - _GLOB_MAX_RESULTS} more files hidden]")
            break

    if not lines:
        return "No files found (all in excluded dirs)."
    return "\n".join(lines)
