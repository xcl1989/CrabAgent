from __future__ import annotations

import fnmatch
import os

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
    ".egg-info",
    "site-packages",
}

# ── Hard limit on how many files to open before aborting ────────────────
_MAX_FILE_SCAN = 10_000


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
                "description": 'File glob pattern to include (e.g. "*.py", "*.{ts,js}").',
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
                "description": (
                    "Maximum directory recursion depth. "
                    "Default: 15. Use -1 for unlimited."
                ),
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
) -> str:
    import re

    # ── Resolve root ────────────────────────────────────────────────────
    root_path = os.path.abspath(path)
    if not os.path.isdir(root_path):
        return f"Error: path does not exist or is not a directory: {path}"

    # ── Compile pattern ─────────────────────────────────────────────────
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    # ── Normalise ignore set ────────────────────────────────────────────
    skip_dirs: set[str] = (
        set(ignore_dirs)
        if ignore_dirs is not None
        else _DEFAULT_IGNORE_DIRS
    )

    # ── Build a file-name filter (fnmatch) from *include* ───────────────
    # We only check the base filename, not the full path, matching the
    # original glob‑like behaviour (e.g.  include="*.py").
    def _match_include(fname: str) -> bool:
        if include is None:
            return True
        return fnmatch.fnmatch(fname, include)

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
            if not _match_include(fname):
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
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
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
        output += (
            "\n[Truncated: showing first 200 matches. "
            "Refine your pattern or path for more precise results.]"
        )
    return output
