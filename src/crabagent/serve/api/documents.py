from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from crabagent.core.config import settings
from crabagent.core.database import User
from crabagent.core.office.manager import get_office_manager
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Supported extensions
_DOC_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
_PREVIEWABLE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}

# ── helpers ───────────────────────────────────────────────────────


def _get_docs_dir(user_id: int, workspace: str = "") -> Path:
    """Get the user's document directory, creating it if needed."""
    if hasattr(settings, "docs_dir") and settings.docs_dir:
        base = Path(settings.docs_dir) / str(user_id)
    else:
        base = Path.home() / ".crabagent" / "docs" / str(user_id)
    if workspace:
        base = base / workspace
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_path(base_dir: Path, file_name: str) -> Path:
    """Resolve a file name safely within base_dir, preventing path traversal."""
    full = base_dir.resolve() / file_name
    full = full.resolve()
    if not str(full).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return full


def _file_info(file_path: Path, base_dir: Path) -> dict:
    """Return a file info dict."""
    stat = file_path.stat()
    rel = str(file_path.relative_to(base_dir))
    ext = file_path.suffix.lower()
    return {
        "name": file_path.name,
        "path": rel,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "type": ext.lstrip("."),
        "previewable": ext in _PREVIEWABLE_EXTENSIONS,
    }


# ── routes ─────────────────────────────────────────────────────────


@router.get("")
async def list_documents(
    workspace: str = "",
    user: User = Depends(get_current_user),
):
    """列出工作区中的 Office 文档。"""
    docs_dir = _get_docs_dir(user.id, workspace)
    files = []
    for f in sorted(docs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in _DOC_EXTENSIONS:
            files.append(_file_info(f, docs_dir))
    return {"files": files, "workspace": workspace, "dir": str(docs_dir)}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    workspace: str = Form(default=""),
    user: User = Depends(get_current_user),
):
    """上传 Office 文档到工作区。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in _DOC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(_DOC_EXTENSIONS)}",
        )

    docs_dir = _get_docs_dir(user.id, workspace)
    dest = _safe_path(docs_dir, file.filename)

    content = await file.read()
    dest.write_bytes(content)

    logger.info("Document uploaded: %s (%d bytes)", dest, len(content))
    return {"status": "ok", "file": file.filename, "size": len(content), "path": str(dest)}


@router.get("/download")
async def download_document(
    path: str,
    workspace: str = "",
    user: User = Depends(get_current_user),
):
    """下载文档。支持 ?path=relative/path 或 ?path=name（工作区根目录）。"""
    docs_dir = _get_docs_dir(user.id, workspace)
    file_path = _safe_path(docs_dir, path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(str(file_path), filename=file_path.name, media_type=media_type)


@router.get("/preview")
async def preview_document(
    path: str,
    workspace: str = "",
    user: User = Depends(get_current_user),
):
    """获取文档的 HTML 预览（需要 OfficeCLI）。"""
    mgr = get_office_manager()
    if not mgr.available:
        raise HTTPException(status_code=503, detail="OfficeCLI is not installed")

    docs_dir = _get_docs_dir(user.id, workspace)
    file_path = _safe_path(docs_dir, path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    if ext not in _PREVIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' is not previewable")

    result = await mgr.view_html(str(file_path))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return {"html": result.data, "file": path, "name": file_path.name}


@router.post("/save")
async def save_document(
    data: dict,
    workspace: str = "",
    user: User = Depends(get_current_user),
):
    """保存从前端编辑器发回的文档内容（base64 编码）。"""
    path = data.get("path", "")
    content_b64 = data.get("content", "")
    if not path or not content_b64:
        raise HTTPException(status_code=400, detail="Missing 'path' or 'content'")

    docs_dir = _get_docs_dir(user.id, workspace)
    file_path = _safe_path(docs_dir, path)

    try:
        content = base64.b64decode(content_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 content")

    # 确保父目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    logger.info("Document saved: %s (%d bytes)", file_path, len(content))
    return {"status": "ok", "file": path, "size": len(content)}


@router.delete("")
async def delete_document(
    path: str,
    workspace: str = "",
    user: User = Depends(get_current_user),
):
    """删除文档。"""
    docs_dir = _get_docs_dir(user.id, workspace)
    file_path = _safe_path(docs_dir, path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_path.unlink()
    logger.info("Document deleted: %s", file_path)
    return {"status": "ok", "file": path}
