from __future__ import annotations

import asyncio
import mimetypes
import socket
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, File as FastFile, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/files", tags=["files"])

# ── Temporary HTTP servers for HTML preview ──────────────────────────
_html_servers: dict[int, asyncio.subprocess.Process] = {}
_html_server_lock = asyncio.Lock()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

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
async def start_http_server(
    path: str = Query(..., description="Absolute directory path to serve"),
    user: User = Depends(get_current_user),
):
    """Start a temporary Python http.server in the given directory for HTML preview."""
    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory or does not exist")

    port = _find_free_port()
    spawn_kwargs: dict = {
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        import subprocess as _sp
        spawn_kwargs["creationflags"] = getattr(_sp, "CREATE_NO_WINDOW", 0)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "http.server", str(port),
        "--directory", str(target),
        **spawn_kwargs,
    )
    async with _html_server_lock:
        _html_servers[port] = proc

    # Wait for the server to actually start listening
    for _ in range(20):
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            break
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.1)
    else:
        proc.terminate()
        raise HTTPException(status_code=500, detail="Preview server failed to start")

    return {"port": port, "url": f"http://localhost:{port}"}


@router.post("/stop-server")
async def stop_http_server(
    port: int = Query(..., description="Port of the server to stop"),
    user: User = Depends(get_current_user),
):
    """Stop a previously started HTTP server."""
    async with _html_server_lock:
        proc = _html_servers.pop(port, None)
    if proc:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        return {"status": "stopped", "port": port}
    return {"status": "not_found", "port": port}


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
