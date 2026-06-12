from __future__ import annotations

import base64
import datetime
import json
import logging
import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

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

    return {"html": _fix_html_newlines(result.data), "file": path, "name": file_path.name}


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


# ── Quick Edit ──────────────────────────────────────────────────────


class StyleChange(BaseModel):
    """一次样式/布局属性的修改。"""
    element: str
    """元素路径，如 /Sheet1/col[A]、/Sheet1/row[3]"""
    props: dict[str, str | int | float | bool]
    """要设置的属性，如 {"width": 20}、{"height": 30, "hidden": True}"""


class QuickEditStyleRequest(BaseModel):
    """请求：批量修改文档中元素的样式/布局属性（行高、列宽等）。"""
    path: str
    workspace: str = ""
    changes: list[StyleChange]


class QuickEditStyleResponse(BaseModel):
    status: str
    preview_html: str | None = None
    results: list[dict] = []
    message: str = ""


class QuickEditTextRequest(BaseModel):
    """请求：通过文本匹配来修改文档中的文字内容。"""

    path: str
    old_text: str
    new_text: str
    workspace: str = ""


class QuickEditTextResponse(BaseModel):
    status: str
    preview_html: str | None = None
    message: str = ""


def _backup_doc(file_path: Path) -> str | None:
    """创建文档的备份副本，返回备份路径；若失败返回 None。"""
    try:
        backup_dir = Path.home() / ".crabagent" / "docs-backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{file_path.stem}_{ts}{file_path.suffix}"
        shutil.copy2(str(file_path), str(backup_path))
        return str(backup_path)
    except Exception as e:
        logger.warning("Backup failed for %s: %s", file_path, e)
        return None


def _fix_html_newlines(html: str | None) -> str | None:
    """OfficeCLI 的 HTML 渲染不把 \\n 转为 <br>，通过在 head 注入 CSS white-space: pre-wrap 让换行可见。"""
    if html:
        # 只在 <head> 或 <html> 开头注入一行 CSS，让所有文本保留换行
        css = "<style>.page, .page-body, .page * { white-space: pre-wrap !important; }</style>\n"
        if "<head>" in html:
            html = html.replace("<head>", "<head>" + css)
        elif "<html" in html:
            html = html.replace("<html", css + "<html")
        else:
            html = css + html
    return html


@router.post("/quick-edit/style", response_model=QuickEditStyleResponse)
async def quick_edit_style(
    req: QuickEditStyleRequest,
    user: User = Depends(get_current_user),
):
    """批量修改文档中元素的样式/布局属性（如行高、列宽、隐藏行/列等）。

    前端拖拽列边框调整宽度后，调用此接口持久化。
    每个 change 对应一次 officecli set 操作。
    """
    mgr = get_office_manager()
    if not mgr.available:
        raise HTTPException(status_code=503, detail="OfficeCLI is not installed")

    docs_dir = _get_docs_dir(user.id, req.workspace)
    file_path = _safe_path(docs_dir, req.path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    if ext not in _PREVIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    if not req.changes:
        raise HTTPException(status_code=400, detail="No changes provided")

    logger.info(
        "[QE-style] %d change(s) on %s",
        len(req.changes), req.path,
    )

    # 修改前备份
    _backup_doc(file_path)

    results: list[dict] = []
    all_ok = True

    for change in req.changes:
        try:
            result = await mgr.set_props(
                str(file_path), change.element, dict(change.props)
            )
            results.append({
                "element": change.element,
                "success": result.success,
                "error": result.error if not result.success else "",
            })
            if not result.success:
                all_ok = False
                logger.warning("[QE-style] Failed: %s → %s", change.element, result.error)
            else:
                logger.info("[QE-style] OK: %s → %s", change.element, change.props)
        except Exception as e:
            results.append({
                "element": change.element,
                "success": False,
                "error": str(e),
            })
            all_ok = False
            logger.exception("[QE-style] Error on %s", change.element)

    # 渲染新预览（即使部分失败也返回，让前端看到当前状态）
    preview_result = await mgr.view_html(str(file_path))
    preview_html = _fix_html_newlines(preview_result.data) if preview_result.success else None

    return QuickEditStyleResponse(
        status="ok" if all_ok else "partial",
        preview_html=preview_html,
        results=results,
        message=f"{len(req.changes)} change(s), {sum(1 for r in results if r['success'])} succeeded",
    )


@router.post("/quick-edit/text", response_model=QuickEditTextResponse)
async def quick_edit_text(
    req: QuickEditTextRequest,
    user: User = Depends(get_current_user),
):
    """通过文本匹配快速修改文档中的文字内容。

    前端用户双击预览中的文字并编辑后，调用此接口。
    后端直接用 OfficeCLI 的 set --find / --replace 全局查找替换，
    无需预先定位元素路径。
    """
    mgr = get_office_manager()
    if not mgr.available:
        raise HTTPException(status_code=503, detail="OfficeCLI is not installed")

    # 解析文件路径
    docs_dir = _get_docs_dir(user.id, req.workspace)
    file_path = _safe_path(docs_dir, req.path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    if ext not in _PREVIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    try:
        old = req.old_text.strip()
        new = req.new_text.strip()
        if not old:
            raise HTTPException(status_code=400, detail="old_text is required")

        logger.info("[QE] old=%s new=%s split=%s", old[:50], new[:50], "\n" in new)

        # 修改前备份
        backup_path = _backup_doc(file_path)
        if backup_path:
            logger.info("[QE] Backed up %s", file_path.name)

        # 判断是否需要分段（新文本含 \n）
        need_split = "\n" in new

        if not need_split:
            logger.info("[QE] Simple text replace")
            # 简单情况：纯文字修改，用 batch set --find/--replace
            batch_cmds = json.dumps([{
                "command": "set",
                "path": "/",
                "props": {"find": old, "replace": new},
            }]).encode("utf-8")
            binary = mgr.binary_path or "/usr/local/bin/officecli"
            result = await mgr._exec_with_stdin(
                [binary, "batch", str(file_path), "--json"],
                stdin_data=batch_cmds,
            )
            if not result.success:
                raise HTTPException(status_code=500, detail=f"Text replace failed: {result.error}")

        else:
            logger.info("[QE] Paragraph split mode: %d segments", len([s for s in new.split("\n") if s.strip()]))
            # 复杂情况：用户按了 Enter，需要把原段落拆成多个段落
            # 1) 用 officecli query "paragraph" --find <old_text> 查找原段落路径
            binary = mgr.binary_path or "/usr/local/bin/officecli"
            query_result = await mgr._exec_with_stdin(
                [binary, "query", str(file_path), "paragraph", "--find", old, "--json"],
            )
            para_path = None
            if query_result.success and isinstance(query_result.data, dict):
                results = query_result.data.get("results", [])
                if results:
                    para_path = results[0].get("path", "")
            if not para_path:
                raise HTTPException(status_code=404, detail=f"Paragraph with text '{old}' not found")

            parent_path = "/body"
            parent_info = await mgr.get_element(str(file_path), parent_path, depth=1)
            para_index = None
            if parent_info.success and isinstance(parent_info.data, dict):
                children = parent_info.data.get("results", [{}])[0].get("children", [])
                for i, child in enumerate(children):
                    if child.get("path") == para_path:
                        para_index = i
                        break

            if para_index is None:
                raise HTTPException(status_code=500, detail="Could not determine paragraph position")

            segments = [s for s in new.split("\n") if s.strip()]
            if not segments:
                raise HTTPException(status_code=400, detail="No content after splitting")

            # batch 删除原段落
            remove_result = await mgr._exec_with_stdin(
                [binary, "batch", str(file_path), "--json"],
                stdin_data=json.dumps([{"command": "remove", "path": para_path}]).encode("utf-8"),
            )
            if not remove_result.success:
                raise HTTPException(status_code=500, detail=f"Remove failed: {remove_result.error}")

            # 逐个插入新段落
            for idx, seg in enumerate(segments):
                add_result = await mgr.exec(
                    "add", str(file_path), parent_path,
                    "--type", "paragraph",
                    "--prop", f"text={seg.strip()}",
                    "--index", str(para_index + idx),
                    "--json",
                )
                if not add_result.success:
                    logger.error("[QE] Add paragraph failed at index %d: %s", para_index + idx, add_result.error)

        # 渲染新预览
        preview_result = await mgr.view_html(str(file_path))
        preview_html = _fix_html_newlines(preview_result.data) if preview_result.success else None

        return QuickEditTextResponse(
            status="ok",
            preview_html=preview_html,
            message="done",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[QE] Unexpected error")
        raise HTTPException(status_code=500, detail=str(e))
