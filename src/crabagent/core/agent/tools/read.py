from __future__ import annotations

from typing import Any

from crabagent.core.agent.multimodal import image_file_to_block, is_image_path
from crabagent.core.agent.token_limits import is_vision_model
from crabagent.core.agent.tools.path_utils import resolve_tool_path
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
        "Read a file or directory from the filesystem. Returns text with line numbers, a directory listing, "
        "or an image inline for direct inspection when the current model supports vision. Prefer this over "
        "a separate vision tool when an image path is already available."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path or workspace-relative path to the file or directory to read.",
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
) -> str | list[dict[str, Any]]:
    path, error = resolve_tool_path(file_path, context)
    if error:
        return error
    assert path is not None
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
    if is_image_path(path):
        model = getattr(context, "model", "") or ""
        if context is not None:
            model = context.metadata.get("_resolved_model", model)
        if model and is_vision_model(model):
            block = image_file_to_block(path)
            if block:
                return [
                    {"type": "text", "text": f"[Image file: {path} — inspect the attached image directly.]"},
                    block,
                ]
        size = path.stat().st_size
        return (
            f"[Image file: {path} ({size:,} bytes)]\n"
            "The current model cannot receive this image directly; use an image analysis tool if needed."
        )

    # Skip other binary files
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
