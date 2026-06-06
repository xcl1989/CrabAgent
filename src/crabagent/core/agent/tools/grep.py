from crabagent.core.agent.tools.registry import registry


@registry.register(
    name="grep",
    description="Search file contents using regular expressions. Returns matching file paths and line numbers.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Default: current directory.",
            },
            "include": {
                "type": "string",
                "description": 'File pattern to include (e.g. "*.py").',
            },
        },
        "required": ["pattern"],
    },
)
def grep_files(pattern: str, path: str = ".", include: str | None = None) -> str:
    import re
    from pathlib import Path

    root = Path(path)
    if not root.exists():
        return f"Error: path does not exist: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    results = []
    glob_pattern = include or "**/*"
    if glob_pattern and not glob_pattern.startswith("**/"):
        glob_pattern = f"**/{glob_pattern}"
    for file_path in root.glob(glob_pattern):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{file_path}:{i}: {line.strip()}")
        except Exception:
            continue

    if not results:
        return "No matches found."
    return "\n".join(results[:200])
