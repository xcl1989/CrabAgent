from __future__ import annotations

import asyncio
import mimetypes
import os
import secrets
import time as _time
from pathlib import Path

from fastapi import APIRouter, Depends, File as FastFile, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/files", tags=["files"])

# ── Temporary HTTP servers for HTML preview ──────────────────────────
_html_servers: dict[str, Path] = {}
_html_server_lock = asyncio.Lock()


def _issue_preview_token(target: Path) -> str:
    token = secrets.token_urlsafe(24)
    _html_servers[token] = target
    return token

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
            if name.startswith(".") and name != ".crabagent":
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


# Directories to skip during search
_SEARCH_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".egg-info", ".next", ".nuxt", ".turbo", ".svelte-kit",
    "target", ".gradle", ".idea", ".vscode",
})

# ── Flat file index cache ────────────────────────────────────────────
# Build once, reuse for all searches until TTL expires.

_file_index_cache: dict[str, list[dict]] = {}  # key: root path → list of {name, path, type}
_file_index_ts: dict[str, float] = {}           # key: root path → build timestamp
_FILE_INDEX_TTL = 15.0  # seconds


def _build_file_index(root: Path, base: Path, absolute: bool) -> list[dict]:
    """Build a flat list of all file/dir entries using os.scandir (fast, no stat calls)."""
    entries: list[dict] = []
    stack = [(root, 20)]  # (dir, depth_remaining)

    while stack:
        dir_path, depth = stack.pop()
        if depth <= 0:
            continue
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith(".") and name != ".crabagent":
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if is_dir and name in _SEARCH_SKIP_DIRS:
                        continue
                    # Compute relative path once
                    full = os.path.join(str(dir_path), name)
                    if absolute:
                        rel = os.path.abspath(full)
                    else:
                        rel = os.path.relpath(full, str(base))
                    entries.append({"name": name, "path": rel, "type": "directory" if is_dir else "file"})
                    if is_dir:
                        stack.append((Path(full), depth - 1))
        except (PermissionError, OSError):
            pass

    return entries


@router.get("/search")
async def search_files(
    q: str = Query(..., min_length=1, description="Search query (matches file/dir names)"),
    path: str = Query("", description="Root path relative to workspace, or absolute path when absolute=true"),
    absolute: bool = Query(False, description="Treat path as absolute filesystem path"),
    limit: int = Query(200, ge=1, le=500, description="Max results"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search file/dir names across the workspace (recursive, case-insensitive).

    Uses a cached flat file index (rebuilt every 15s) for instant filtering.
    """
    from crabagent.core.config import settings

    if absolute:
        root = Path(path).resolve() if path else Path("/")
    else:
        workspace = settings.workspace.resolve()
        root = _resolve_path(workspace, path.lstrip("/"))
        if not root:
            raise HTTPException(status_code=400, detail="Path outside workspace")

    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    cache_key = str(root)

    def _ensure_index() -> list[dict]:
        """Return cached index or rebuild if stale."""
        now = _time.monotonic()
        if (
            cache_key in _file_index_cache
            and (now - _file_index_ts.get(cache_key, 0)) < _FILE_INDEX_TTL
        ):
            return _file_index_cache[cache_key]
        # Build fresh index
        base = root if absolute else _resolve_path(settings.workspace.resolve(), "") or root
        idx = _build_file_index(root, base, absolute)
        _file_index_cache[cache_key] = idx
        _file_index_ts[cache_key] = now
        return idx

    # Run index build in thread pool (only hits filesystem on cache miss)
    index = await asyncio.to_thread(_ensure_index)

    # Filter — pure in-memory, instant.
    # Match against both file name and path for better discoverability.
    query_lower = q.lower()
    results = [e for e in index if query_lower in e["name"].lower() or query_lower in e["path"].lower()]
    return {"results": results[:limit], "total": len(results)}


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


@router.post("/write")
async def write_file(
    req: WriteFileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from crabagent.core.config import settings

    if req.absolute:
        target = Path(req.path).resolve()
        if not str(target).startswith(str(Path.home())):
            raise HTTPException(status_code=400, detail="Absolute path must be under home directory")
    else:
        workspace = settings.workspace.resolve()
        t = _resolve_path(workspace, req.path.lstrip("/"))
        if not t:
            raise HTTPException(status_code=400, detail="Path outside workspace")
        target = t

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content, encoding="utf-8")
        return {"status": "ok", "path": req.path, "size": target.stat().st_size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")


class WriteFileRequest(BaseModel):
    path: str
    content: str
    absolute: bool = False


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


@router.get("/serve/{file_path:path}")
async def serve_file(
    file_path: str,
    token: str = Query(..., description="JWT token for auth"),
    db: AsyncSession = Depends(get_db),
):
    """Serve any file with correct Content-Type.
    
    Path is treated as absolute filesystem path (with leading /) or
    relative to workspace. Uses token query param for auth (same as /files/image).
    """
    from crabagent.core.config import settings
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id
    from fastapi.responses import HTMLResponse

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

    if file_path.startswith("/"):
        target = Path(file_path).resolve()
    else:
        workspace = settings.workspace.resolve()
        t = _resolve_path(workspace, file_path.lstrip("/"))
        if not t:
            raise HTTPException(status_code=400, detail="Path outside workspace")
        target = t

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(str(target), media_type=media_type)


@router.post("/serve-dir")
async def start_preview_session(
    path: str = Query(..., description="Absolute directory path to preview"),
    user: User = Depends(get_current_user),
):
    """Create a tokenized same-origin preview route for a directory."""
    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory or does not exist")

    async with _html_server_lock:
        preview_token = _issue_preview_token(target)

    return {"token": preview_token, "url": f"/api/files/preview/{preview_token}"}


@router.get("/preview/{preview_token}/{file_path:path}")
async def serve_preview_file(
    preview_token: str,
    file_path: str,
):
    """Serve files in a preview session. The preview_token is self-authenticating."""
    async with _html_server_lock:
        base_dir = _html_servers.get(preview_token)
    if not base_dir:
        raise HTTPException(status_code=404, detail="Preview session not found")

    target = _resolve_path(base_dir, file_path)
    if not target or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(str(target), media_type=media_type)


@router.post("/stop-server")
async def stop_preview_session(
    token: str = Query(..., description="Preview session token to stop"),
    user: User = Depends(get_current_user),
):
    async with _html_server_lock:
        removed = _html_servers.pop(token, None)
    return {"status": "stopped" if removed else "not_found", "token": token}


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
        status_lines = stdout.decode("utf-8", errors="replace").splitlines()

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
        MAX_DIFF = 50_000

        # Check if the file is untracked (??). git diff doesn't show untracked files,
        # so we need to use --no-index against /dev/null.
        if path:
            status_proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain", "--", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws),
            )
            status_stdout, _ = await asyncio.wait_for(status_proc.communicate(), timeout=10)
            status_line = status_stdout.decode("utf-8", errors="replace").strip()
            if status_line.startswith("??"):
                # Untracked file: diff against /dev/null to show full content as added
                full_path = ws / path
                if full_path.is_file():
                    # Limit file size to avoid huge diffs
                    file_size = full_path.stat().st_size
                    if file_size > 100_000:
                        diff_text = f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n(file too large to display: {file_size} bytes)"
                        return {"is_git": True, "diff": diff_text, "truncated": True}
                    try:
                        file_content = full_path.read_text("utf-8", errors="replace")
                    except Exception:
                        file_content = "(binary file)"
                    diff_lines = [f"diff --git a/{path} b/{path}", "new file mode 100644",
                                  "--- /dev/null", f"+++ b/{path}"]
                    for i, line in enumerate(file_content.splitlines(), 1):
                        diff_lines.append(f"+{line}")
                    diff_text = "\n".join(diff_lines)
                    truncated = False
                    if len(diff_text) > MAX_DIFF:
                        diff_text = diff_text[:MAX_DIFF]
                        truncated = True
                    return {"is_git": True, "diff": diff_text, "truncated": truncated}
                else:
                    return {"is_git": True, "diff": "", "is_untracked_dir": True}

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
        truncated = False
        if len(diff_text) > MAX_DIFF:
            diff_text = diff_text[:MAX_DIFF]
            truncated = True

        return {"is_git": True, "diff": diff_text, "truncated": truncated}

    except Exception as e:
        return {"is_git": True, "diff": "", "error": str(e)}


# ── File management: delete / rename / create / download ─────────────


def _resolve_file_path(raw_path: str, absolute: bool = False) -> Path:
    """Resolve a file path safely, preventing path traversal."""
    if absolute:
        target = Path(raw_path).resolve()
        if not str(target).startswith(str(Path.home())):
            raise HTTPException(status_code=400, detail="Absolute path must be under home directory")
        return target
    else:
        from crabagent.core.config import settings

        workspace = settings.workspace.resolve()
        t = _resolve_path(workspace, raw_path.lstrip("/"))
        if not t:
            raise HTTPException(status_code=400, detail="Path outside workspace")
        return t


class DeleteRequest(BaseModel):
    path: str
    absolute: bool = False


class RenameRequest(BaseModel):
    old_path: str
    new_path: str
    absolute: bool = False


class CreateRequest(BaseModel):
    path: str
    entry_type: str = "file"  # "file" or "directory"
    absolute: bool = False


@router.delete("/manage")
async def delete_entry(
    req: DeleteRequest,
    user: User = Depends(get_current_user),
):
    """Delete a file or directory."""
    import shutil

    target = _resolve_file_path(req.path, req.absolute)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"status": "ok", "path": req.path}


@router.post("/rename")
async def rename_entry(
    req: RenameRequest,
    user: User = Depends(get_current_user),
):
    """Rename or move a file/directory."""
    old = _resolve_file_path(req.old_path, req.absolute)
    new = _resolve_file_path(req.new_path, req.absolute)
    if not old.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    if new.exists():
        raise HTTPException(status_code=409, detail="Target already exists")
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    return {"status": "ok", "old_path": req.old_path, "new_path": req.new_path}


@router.post("/create")
async def create_entry(
    req: CreateRequest,
    user: User = Depends(get_current_user),
):
    """Create a new file or directory."""
    target = _resolve_file_path(req.path, req.absolute)
    if target.exists():
        raise HTTPException(status_code=409, detail="Path already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    if req.entry_type == "directory":
        target.mkdir(parents=True)
    else:
        target.write_text("", encoding="utf-8")
    return {"status": "ok", "path": req.path, "type": req.entry_type}


@router.get("/download")
async def download_file(
    path: str = Query(...),
    absolute: bool = Query(False),
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Download a file with token auth (for direct browser download)."""
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_user_by_id(db, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    target = _resolve_file_path(path, absolute)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), filename=target.name, media_type=media_type)


# ── General file upload ─────────────────────────────────────────────


def _get_uploads_dir(user_id: int) -> Path:
    """Get the user's uploads directory, creating it if needed."""
    base = Path.home() / ".crabagent" / "uploads" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


# Max upload size: 20 MB
_MAX_UPLOAD_SIZE = 20 * 1024 * 1024


@router.post("/upload")
async def upload_file(
    file: UploadFile = FastFile(...),
    user: User = Depends(get_current_user),
):
    """Upload any file to the user's uploads directory.

    Files are stored in ~/.crabagent/uploads/{user_id}/ — NOT in the workspace.
    Returns the absolute path so the agent can read the file.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20MB)")

    uploads_dir = _get_uploads_dir(user.id)

    # Sanitize filename — prevent path traversal
    safe_name = Path(file.filename).name
    dest = uploads_dir / safe_name

    # Avoid overwriting: append timestamp suffix if file exists
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        import time as _time

        dest = uploads_dir / f"{stem}_{int(_time.time())}{suffix}"

    dest.write_bytes(content)

    return {
        "status": "ok",
        "file": file.filename,
        "size": len(content),
        "path": str(dest),
    }
