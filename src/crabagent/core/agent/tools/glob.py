from __future__ import annotations

import os
import re
from typing import Any

from crabagent.core.agent.tools.registry import registry

# ── Directories always excluded from search ─────────────────────────────
_GLOB_EXCLUDE_DIRS = {
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

_GLOB_MAX_RESULTS = 500
_GLOB_MAX_SCAN = 50_000  # safety valve


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern to a compiled regex.

    Supports standard glob metacharacters plus ``**`` for recursive
    (cross-directory) matching, and brace expansion like ``{ts,tsx}``.

    - ``**`` matches any path segments (including zero)
    - ``*`` matches anything except ``/``
    - ``?`` matches a single non-slash character
    - ``[seq]`` matches any character in *seq*
    """
    # ── Expand brace groups first ──
    # e.g. "*.{ts,tsx,js}" → ["*.ts", "*.tsx", "*.js"]
    brace_re = re.compile(r"\{([^}]+)\}")
    patterns: list[str] = []
    m = brace_re.search(pattern)
    if m:
        prefix = pattern[: m.start()]
        suffix = pattern[m.end() :]
        for opt in m.group(1).split(","):
            patterns.extend(_glob_to_regex_list(f"{prefix}{opt}{suffix}"))
    else:
        patterns.append(pattern)

    # ── Convert each sub-pattern to regex ──
    regex_parts: list[str] = []
    for sub in patterns:
        parts: list[str] = []
        i = 0
        while i < len(sub):
            two = sub[i : i + 2]
            ch = sub[i]
            if two == "**":
                # **/ → match any path prefix (including empty)
                # ** at end → match anything remaining
                parts.append(".*")
                i += 2
                # Skip optional trailing /
                if i < len(sub) and sub[i] == "/":
                    i += 1
            elif ch == "*":
                parts.append("[^/]*")
                i += 1
            elif ch == "?":
                parts.append("[^/]")
                i += 1
            elif ch == "[":
                # Character class — copy as-is until ]
                end = sub.find("]", i + 1)
                if end == -1:
                    parts.append(re.escape(ch))
                    i += 1
                else:
                    parts.append(sub[i : end + 1])
                    i = end + 1
            else:
                parts.append(re.escape(ch))
                i += 1
        regex_parts.append("".join(parts))

    # Combine multiple sub-patterns with |
    combined = "|".join(f"(?:{p})" for p in regex_parts)
    return re.compile(f"^(?:{combined})$")


def _glob_to_regex_list(pattern: str) -> list[str]:
    """Helper for recursive brace expansion (returns raw strings)."""
    brace_re = re.compile(r"\{([^}]+)\}")
    m = brace_re.search(pattern)
    if not m:
        return [pattern]
    prefix = pattern[: m.start()]
    suffix = pattern[m.end() :]
    result: list[str] = []
    for opt in m.group(1).split(","):
        expanded = f"{prefix}{opt}{suffix}"
        # Recurse in case of nested braces
        result.extend(_glob_to_regex_list(expanded))
    return result


@registry.register(
    name="glob",
    description=(
        "Find files matching a glob pattern. Returns sorted relative file paths. "
        "Supports ** for recursive matching and brace expansion like "
        "'*.{ts,tsx,js}'. Excludes common dependency/cache directories."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Glob pattern (e.g. '**/*.py', 'src/**/*.tsx', '*.{ts,js}'). "
                    "** matches across directories, * matches within one level."
                ),
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Default: current directory.",
            },
            "ignore_dirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("Directory names to skip. Defaults to common dependency/cache directories."),
            },
        },
        "required": ["pattern"],
    },
)
def glob_files(
    pattern: str,
    path: str = ".",
    ignore_dirs: list[str] | None = None,
    context: Any = None,
) -> str:
    # ── Resolve root (prefer workspace context when available) ──────────
    base = path
    if context is not None and hasattr(context, "workspace") and context.workspace:
        try:
            import pathlib

            p = pathlib.Path(path)
            if not p.is_absolute():
                base = str(pathlib.Path(context.workspace) / path)
        except Exception:
            pass

    root = os.path.abspath(base)
    if not os.path.exists(root):
        return f"Error: path does not exist: {path}"
    if os.path.isfile(root):
        return f"Error: path is a file, not a directory: {path}"

    # ── Prepare exclude set ─────────────────────────────────────────────
    skip_dirs = set(ignore_dirs) if ignore_dirs is not None else _GLOB_EXCLUDE_DIRS

    # ── Compile glob pattern to regex ───────────────────────────────────
    try:
        matcher = _glob_to_regex(pattern)
    except re.error as e:
        return f"Error: invalid glob pattern: {e}"

    # ── Walk with directory pruning ─────────────────────────────────────
    # Build a set of matching relative paths
    matches: list[str] = []
    scanned = 0

    for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
        # Prune excluded directories in-place (never descend into them)
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for fname in files:
            scanned += 1
            if scanned > _GLOB_MAX_SCAN:
                matches.append(
                    f"\n... [TRUNCATED: scanned over {_GLOB_MAX_SCAN:,} files. "
                    "Narrow your search with a more specific path or pattern.]"
                )
                # Sort what we have and return
                matches = sorted(set(matches))
                return "\n".join(matches[:_GLOB_MAX_RESULTS])

            # Build relative path from root
            rel_dir = os.path.relpath(current_root, root)
            if rel_dir == ".":
                rel_path = fname
            else:
                rel_path = os.path.join(rel_dir, fname)
            # Normalise separators for cross-platform matching
            rel_path_norm = rel_path.replace(os.sep, "/")

            if matcher.match(rel_path_norm):
                matches.append(rel_path_norm)

    if not matches:
        return "No files found matching pattern."

    matches = sorted(set(matches))
    if len(matches) > _GLOB_MAX_RESULTS:
        lines = matches[:_GLOB_MAX_RESULTS]
        lines.append(f"\n... [truncated: {len(matches) - _GLOB_MAX_RESULTS} more files hidden]")
        return "\n".join(lines)

    return "\n".join(matches)
