from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/files", tags=["files"])


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
