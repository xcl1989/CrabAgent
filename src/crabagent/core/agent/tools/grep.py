from __future__ import annotations

import fnmatch
import os
import re
from typing import Any

from crabagent.core.agent.tools.path_utils import resolve_tool_path
from crabagent.core.agent.tools.registry import registry

# ── Default directories to skip when searching ──────────────────────────
_DEFAULT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".npm",
    ".cargo",
    "Library",
    ".venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".egg-info",
    ".eggs",
    "site-packages",
    "molts",
    ".opencode",
    "venv",
}

# ── Hard limit on how many files to open before aborting ────────────────
_MAX_FILE_SCAN = 10_000

# ── Skip files larger than this (avoid reading huge binaries/logs) ──────
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _expand_braces(pattern: str) -> list[str]:
    """Expand shell-style brace patterns like ``*.{ts,js}`` into a list
    of plain patterns: ``["*.ts", "*.js"]``.

    ``fnmatch`` does not support ``{a,b}`` syntax, so we expand it
    ourselves before calling ``fnmatch``.
    """
    # Handle at most one brace group per pattern (covers the vast majority
    # of real-world cases like *.{py,pyi} or *.{ts,tsx,js}).
    m = re.search(r"\{([^}]+)\}", pattern)
    if not m:
        return [pattern]
    prefix = pattern[: m.start()]
    suffix = pattern[m.end() :]
    options = m.group(1).split(",")
    return [f"{prefix}{opt}{suffix}" for opt in options]


def _match_include(fname: str, patterns: list[str]) -> bool:
    """Check whether *fname* matches any of the include patterns."""
    for pat in patterns:
        if fnmatch.fnmatch(fname, pat):
            return True
    return False


def _is_binary(filepath: str) -> bool:
    """Quick heuristic: read first 4KB and check for NUL bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except (OSError, PermissionError):
        return True  # if we can't even read it, treat as binary/skip


@registry.register(
    name="grep",
    description=(
        "Search file contents using regular expressions. "
        "Returns matching file paths and line numbers. "
        "Supports skipping common build/dependency directories and a "
        "configurable maximum search depth to avoid runaway traversals."
    ),
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
                "description": (
                    'File glob pattern to filter files (e.g. "*.py"). '
                    "Supports brace expansion: '*.{ts,tsx,js}' matches "
                    "all three extensions."
                ),
            },
            "ignore_dirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Directory names to skip during recursive search. "
                    "Defaults to common build/dependency/cache directories "
                    "(.git, node_modules, __pycache__, .npm, .cargo, Library, "
                    ".venv, dist, build, .mypy_cache, .pytest_cache, .egg-info, "
                    "site-packages). Set to an empty list to disable skipping."
                ),
            },
            "max_depth": {
                "type": "integer",
                "description": ("Maximum directory recursion depth. Default: 15. Use -1 for unlimited."),
            },
        },
        "required": ["pattern"],
    },
)
def grep_files(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    ignore_dirs: list[str] | None = None,
    max_depth: int = 15,
    context: Any = None,
) -> str:
    resolved_path, error = resolve_tool_path(path, context)
    if error:
        return error
    assert resolved_path is not None

    # ── Single-file mode: if *path* is a file, grep it directly ────────
    resolved = os.path.abspath(str(resolved_path))
    if os.path.isfile(resolved):
        try:
            regex_inner = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex: {e}"
        single_results: list[str] = []
        try:
            if os.path.getsize(resolved) <= _MAX_FILE_SIZE and not _is_binary(resolved):
                with open(resolved, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex_inner.search(line):
                            single_results.append(f"{resolved}:{lineno}: {line.rstrip()}")
                            if len(single_results) >= 200:
                                single_results.append("[Truncated: showing first 200 matches.]")
                                break
        except (OSError, PermissionError):
            return f"Error: cannot read file: {resolved}"
        if not single_results:
            return "No matches found."
        return "\n".join(single_results)

    # ── Directory mode ──────────────────────────────────────────────────
    root_path = resolved
    if not os.path.isdir(root_path):
        return f"Error: path does not exist or is not a directory: {path}"

    # ── Compile pattern ─────────────────────────────────────────────────
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    # ── Normalise ignore set ────────────────────────────────────────────
    skip_dirs: set[str] = set(ignore_dirs) if ignore_dirs is not None else _DEFAULT_IGNORE_DIRS

    # ── Build include patterns (with brace expansion) ───────────────────
    include_patterns = _expand_braces(include) if include else []

    results: list[str] = []
    scanned = 0

    # ── os.walk with pruning, depth tracking & size limit ───────────────
    # Compute the depth of root_path so we can measure relative depth.
    root_depth = root_path.rstrip(os.sep).count(os.sep)

    for current_root, dirs, files in os.walk(root_path, topdown=True, followlinks=False):
        # --- Depth guard ---
        if max_depth >= 0:
            current_depth = current_root.rstrip(os.sep).count(os.sep) - root_depth
            if current_depth > max_depth:
                # Do NOT descend further.
                dirs[:] = []
                continue

        # --- Prune ignored directories (mutate dirs in-place) ---
        # This prevents os.walk from ever entering them.
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        # --- Process files ---
        for fname in files:
            if include_patterns:
                if not _match_include(fname, include_patterns):
                    continue

            scanned += 1
            if scanned > _MAX_FILE_SCAN:
                results.append(
                    f"[TRUNCATED] Searched over {_MAX_FILE_SCAN:,} files — "
                    "scope too broad. Narrow your search with a more specific "
                    "path, pattern, or include filter."
                )
                # Flush what we have and stop.
                if results:
                    return "\n".join(results[:200])
                return (
                    f"Search scope too broad (>{_MAX_FILE_SCAN:,} files). "
                    "Please narrow your search with a more specific path, "
                    "pattern, or include filter."
                )

            fpath = os.path.join(current_root, fname)
            try:
                # Skip oversized files and binary files
                if os.path.getsize(fpath) > _MAX_FILE_SIZE:
                    continue
                if _is_binary(fpath):
                    continue
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            results.append(f"{fpath}:{lineno}: {line.rstrip()}")
                            if len(results) >= 200:
                                break
                    if len(results) >= 200:
                        break
            except Exception:
                continue

        if len(results) >= 200:
            break

    if not results:
        return "No matches found."

    output = "\n".join(results[:200])
    if len(results) == 200:
        output += "\n[Truncated: showing first 200 matches. Refine your pattern or path for more precise results.]"
    return output
