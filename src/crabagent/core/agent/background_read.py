"""Conservative, descriptor-relative workspace reading for background agents.

This is not a content-based secret scanner or an OS sandbox. Only explicitly
allowed source/document extensions are accessible; hidden paths and symlinks
(including internal symlinks) are rejected.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from crabagent.core.agent.tools.registry import ToolRegistry

_MAX_BYTES = 256 * 1024
_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".html",
        ".md",
        ".rst",
        ".txt",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rs",
        ".go",
        ".swift",
        ".kt",
        ".sql",
        ".sh",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
    }
)
_SENSITIVE = (
    "secret",
    "credential",
    "password",
    "passwd",
    "token",
    "private",
    "apikey",
    "api_key",
    "api-key",
    "id_rsa",
    "id_ed25519",
)


def read_workspace_file(file_path: str, offset: int = 1, limit: int = 2000, context=None) -> str:
    if context is None or not isinstance(file_path, str) or not file_path or "\x00" in file_path:
        return "Error: invalid path"
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 1
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 2000
    ):
        return "Error: invalid offset or limit"
    root = Path(context.workspace)
    if not root.is_absolute():
        root = Path(os.path.abspath(root))
    path = Path(file_path)
    try:
        if path.is_absolute():
            path = path.relative_to(root)
        parts = path.parts
        if not parts or any(
            p in (".", "..") or p.startswith(".") or any(s in p.lower() for s in _SENSITIVE) for p in parts
        ):
            raise ValueError
        if path.suffix.lower() not in _EXTENSIONS:
            raise ValueError
        # Walk using directory descriptors and O_NOFOLLOW, preventing check/open
        # races and symlink traversal even when a directory is replaced concurrently.
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ValueError
        fds = []
        try:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            fds.append(root_fd)
            for part in parts[:-1]:
                fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
            fds.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_BYTES:
                raise ValueError
            data = b""
            while len(data) <= _MAX_BYTES:
                chunk = os.read(fd, min(65536, _MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
            if len(data) > _MAX_BYTES or b"\x00" in data:
                raise ValueError
            lines = data.decode("utf-8").splitlines()
            return (
                "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1) if offset <= i < offset + limit)
                or "(empty)"
            )
        finally:
            for fd in reversed(fds):
                os.close(fd)
    except (OSError, ValueError, UnicodeError):
        return "Error: path unavailable or not permitted"


def register_safe_read(registry: ToolRegistry) -> None:
    registry.register(
        name="read",
        description=("Read permitted UTF-8 workspace files. Hidden, sensitive-named, linked, large and "
                     "non-allowlisted files are denied. Not a secret scanner or sandbox."),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Workspace-relative or absolute file path."},
                "offset": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 2000},
            },
            "required": ["file_path"],
        },
    )(read_workspace_file)
