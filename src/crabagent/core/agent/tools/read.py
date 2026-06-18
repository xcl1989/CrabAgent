from __future__ import annotations

from typing import Any

from crabagent.core.agent.tools.registry import registry

# Shared exclude set — keep in sync with glob.py and grep.py
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    ".venv",
    "venv",
    ".eggs",
    ".egg-info",
    "dist",
    "build",
    "molts",
    ".opencode",
    "site-packages",
    ".npm",
    ".cargo",
}


def _is_binary(filepath: str) -> bool:
    """Quick heuristic: read first 4KB and check for NUL bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except (OSError, PermissionError):
        return True


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
def read_file(
    file_path: str,
    offset: int = 1,
    limit: int = 2000,
    context: Any = None,
) -> str:
    from pathlib import Path

    # ── Resolve path (prefer workspace context when available) ──────────
    base = file_path
    if context is not None and hasattr(context, "workspace") and context.workspace:
        try:
            p = Path(file_path)
            if not p.is_absolute():
                base = str(Path(context.workspace) / file_path)
        except Exception:
            pass

    path = Path(base)
    if not path.exists():
        return f"Error: path does not exist: {file_path}"

    # ── Directory listing ───────────────────────────────────────────────
    if path.is_dir():
        entries = []
        for entry in sorted(path.iterdir()):
            # Only skip known noise directories; show dotfiles (.env, .gitignore, etc.)
            if entry.is_dir() and entry.name in _SKIP_DIRS:
                continue
            suffix = "/" if entry.is_dir() else ""
            entries.append(entry.name + suffix)
        return "\n".join(entries) if entries else "(empty directory)"

    # ── File reading ────────────────────────────────────────────────────
    # Skip binary files
    if _is_binary(str(path)):
        size = path.stat().st_size
        return (
            f"[Binary file: {file_path} ({size:,} bytes)]\n"
            f"Binary content not displayed. Use a specialized tool to inspect."
        )

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
