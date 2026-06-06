from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/files", tags=["files"])

_IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif"}
)


def _resolve_path(base: Path, raw: str) -> Path | None:
    resolved = (base / raw).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


@router.get("/tree")
async def list_tree(
    path: str = Query("", description="Path relative to workspace, or absolute path when absolute=true"),
    depth: int = Query(1, ge=1, le=5),
    absolute: bool = Query(False, description="Treat path as absolute filesystem path"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings

    if absolute:
        target = Path(path).resolve() if path else Path("/")
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")
        return _build_tree(target, target, depth=depth, absolute=True)

    workspace = settings.workspace.resolve()
    target = _resolve_path(workspace, path.lstrip("/"))
    if not target:
        raise HTTPException(status_code=400, detail="Path outside workspace")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    return _build_tree(target, workspace, depth=depth)


def _build_tree(dir_path: Path, base: Path, depth: int, absolute: bool = False) -> list[dict]:
    if depth <= 0:
        return []
    entries: list[dict] = []
    try:
        for child in sorted(dir_path.iterdir()):
            name = child.name
            if name.startswith("."):
                continue
            rel = str(child.resolve()) if absolute else str(child.relative_to(base))
            is_dir = child.is_dir()
            entry: dict = {"name": name, "path": rel, "type": "directory" if is_dir else "file"}
            if is_dir and depth > 1:
                entry["children"] = _build_tree(child, base, depth - 1, absolute)
            entries.append(entry)
    except PermissionError:
        pass
    return entries


@router.get("/read")
async def read_file(
    path: str = Query(..., description="Relative path from workspace, or absolute path when absolute=true"),
    absolute: bool = Query(False, description="Treat path as absolute filesystem path"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings

    if absolute:
        target = Path(path).resolve()
    else:
        workspace = settings.workspace.resolve()
        t = _resolve_path(workspace, path.lstrip("/"))
        if not t:
            raise HTTPException(status_code=400, detail="Path outside workspace")
        target = t

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    MAX_SIZE = 1024 * 1024
    if target.stat().st_size > MAX_SIZE:
        return {"path": path, "content": "", "truncated": True, "message": "File too large (>1MB)"}

    try:
        content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, Exception):
        content = ""

    return {"path": path, "content": content, "truncated": False}


@router.get("/image")
async def get_image(
    path: str = Query(..., description="Relative path from workspace, or absolute path when absolute=true"),
    absolute: bool = Query(False, description="Treat path as absolute filesystem path"),
    token: str = Query(..., description="JWT token for img src auth"),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = await get_user_by_id(db, user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    if absolute:
        target = Path(path).resolve()
    else:
        workspace = settings.workspace.resolve()
        t = _resolve_path(workspace, path.lstrip("/"))
        if not t:
            raise HTTPException(status_code=400, detail="Path outside workspace")
        target = t

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if target.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an image file")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(str(target), media_type=media_type)


@router.get("/git-status")
async def git_status(
    workspace: str | None = Query(None, description="Absolute workspace path"),
    user: User = Depends(get_current_user),
):
    """Return git status and diff for the workspace if it's a git repo."""
    import asyncio

    from crabagent.core.config import settings as _settings

    ws = Path(workspace).resolve() if workspace else _settings.workspace.resolve()
    if not ws.is_dir() or not (ws / ".git").exists():
        return {"is_git": False, "changes": []}

    try:
        # git status --porcelain
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        status_lines = stdout.decode("utf-8", errors="replace").strip().splitlines()

        changes = []
        for line in status_lines:
            if len(line) < 4:
                continue
            status_code = line[:2].strip()
            filepath = line[3:].strip()
            # Handle renames: "R  old -> new"
            if "->" in filepath:
                parts = filepath.split("->")
                filepath = parts[-1].strip().strip('"')
            else:
                filepath = filepath.strip('"')
            changes.append({"status": status_code, "file": filepath})

        # git diff --stat for changed lines summary
        diff_summary = ""
        if changes:
            proc2 = await asyncio.create_subprocess_exec(
                "git", "diff", "--stat",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws),
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)
            diff_summary = stdout2.decode("utf-8", errors="replace").strip()

        return {"is_git": True, "changes": changes, "diff_summary": diff_summary}

    except Exception as e:
        return {"is_git": True, "changes": [], "error": str(e)}


@router.get("/git-diff")
async def git_diff(
    path: str | None = Query(None, description="Specific file path, or all changes if omitted"),
    cached: bool = Query(False, description="Show staged changes"),
    workspace: str | None = Query(None, description="Absolute workspace path"),
    user: User = Depends(get_current_user),
):
    """Return git diff output for the workspace."""
    import asyncio

    from crabagent.core.config import settings as _settings

    ws = Path(workspace).resolve() if workspace else _settings.workspace.resolve()
    if not ws.is_dir() or not (ws / ".git").exists():
        return {"is_git": False, "diff": ""}

    try:
        args = ["git", "diff"]
        if cached:
            args.append("--cached")
        if path:
            args.extend(["--", path])

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        diff_text = stdout.decode("utf-8", errors="replace")

        # Truncate if too large
        MAX_DIFF = 50_000
        truncated = False
        if len(diff_text) > MAX_DIFF:
            diff_text = diff_text[:MAX_DIFF]
            truncated = True

        return {"is_git": True, "diff": diff_text, "truncated": truncated}

    except Exception as e:
        return {"is_git": True, "diff": "", "error": str(e)}
