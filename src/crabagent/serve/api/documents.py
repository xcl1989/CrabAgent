from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
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


async def _ensure_officecli() -> bool:
    """确保 OfficeCLI 可用，自动检测+后台自动安装。

    如果安装需要时间，会在后台启动安装任务并返回 False，
    前端可通过 ``GET /api/officecli/status`` 轮询进度。

    Returns:
        True — OfficeCLI 已就绪，可以直接使用
        False — 安装任务已启动，需要等待完成

    Raises:
        HTTPException(503) — 安装已失败，不再重试
    """
    mgr = get_office_manager()
    if mgr.available:
        return True
    if await mgr.detect():
        return True

    status = mgr.get_install_status()

    # 安装已失败 → 直接报错，不再重试
    if status["status"] == "failed":
        raise HTTPException(status_code=503, detail=status.get("message", "OfficeCLI installation failed"))

    # 正在安装中 → 返回 False，前端继续轮询
    if status["status"] == "installing":
        return False

    # 未安装 → 后台启动安装
    mgr._install_task = asyncio.create_task(mgr.install())
    return False


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
    if not await _ensure_officecli():
        return JSONResponse(status_code=503, content={
            "detail": "OfficeCLI is being installed, please retry",
            "installing": True,
        })
    mgr = get_office_manager()
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
    if not await _ensure_officecli():
        return JSONResponse(status_code=503, content={"installing": True, "detail": "OfficeCLI is being installed"})
    mgr = get_office_manager()

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
    if not await _ensure_officecli():
        return JSONResponse(status_code=503, content={"installing": True, "detail": "OfficeCLI is being installed"})
    mgr = get_office_manager()

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
            binary = mgr.binary_path
            if not binary:
                raise HTTPException(status_code=503, detail="OfficeCLI is not installed")
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
            binary = mgr.binary_path
            if not binary:
                raise HTTPException(status_code=503, detail="OfficeCLI is not installed")
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


# ── Quick Edit: structured table operations ───────────────────────────


class TableOpRequest(BaseModel):
    """请求：结构化表格操作（插入/删除行列、合并/取消合并、设置公式等）。"""

    path: str
    workspace: str = ""
    operation: str
    """操作类型：insert_row | delete_row | insert_col | delete_col |
    merge_cells | unmerge_cells | set_formula | set_cell_style"""
    sheet: str = "Sheet1"
    """Excel 工作表名"""
    params: dict = {}
    """操作参数，具体取决于 operation 类型：
    - insert_row: {after_row: int} 或 {before_row: int}
    - delete_row: {row: int}
    - insert_col: {col_letter: str} 或 {after_col: str}
    - delete_col: {col_letter: str}
    - merge_cells: {range: str}  如 "A1:C3"
    - unmerge_cells: {range: str}
    - set_formula: {cell: str, formula: str}
    - set_cell_style: {cell: str, props: dict}
    """


class TableOpResponse(BaseModel):
    status: str
    preview_html: str | None = None
    message: str = ""
    error: str = ""


def _build_batch_cmd(req: TableOpRequest) -> dict | None:
    """将结构化操作转换为 officecli batch 命令。"""
    op = req.operation
    p = req.params
    sheet = req.sheet

    if op == "insert_row":
        cmd: dict = {"command": "add", "parent": f"/{sheet}", "type": "row", "props": {"cols": p.get("cols", 1)}}
        if "after_row" in p:
            cmd["after"] = f"/{sheet}/row[{p['after_row']}]"
        elif "before_row" in p:
            cmd["before"] = f"/{sheet}/row[{p['before_row']}]"
        return cmd

    if op == "delete_row":
        return {"command": "remove", "path": f"/{sheet}/row[{p['row']}]"}

    if op == "insert_col":
        cmd = {"command": "add", "parent": f"/{sheet}", "type": "column", "props": {}}
        if "col_letter" in p:
            cmd["props"]["name"] = p["col_letter"]
        if "after_col" in p:
            cmd["after"] = f"/{sheet}/col[{p['after_col']}]"
        return cmd

    if op == "delete_col":
        return {"command": "remove", "path": f"/{sheet}/col[{p['col_letter']}]"}

    if op == "merge_cells":
        cell_range = p.get("range", "")
        if not cell_range:
            return None
        return {"command": "set", "path": f"/{sheet}/{cell_range}", "props": {"merge": True}}

    if op == "unmerge_cells":
        cell_range = p.get("range", "")
        if not cell_range:
            return None
        return {"command": "set", "path": f"/{sheet}/{cell_range}", "props": {"merge": False}}

    if op == "set_formula":
        cell = p.get("cell", "")
        formula = p.get("formula", "")
        if not cell or not formula:
            return None
        return {"command": "set", "path": f"/{sheet}/{cell}", "props": {"formula": formula}}

    if op == "set_cell_style":
        cell = p.get("cell", "")
        props = p.get("props", {})
        if not cell or not props:
            return None
        return {"command": "set", "path": f"/{sheet}/{cell}", "props": props}

    return None


@router.post("/quick-edit/table-op", response_model=TableOpResponse)
async def quick_edit_table_op(
    req: TableOpRequest,
    user: User = Depends(get_current_user),
):
    """执行结构化表格操作（插入/删除行列、合并/取消合并、设置公式等）。

    前端表格操作按钮（合并单元格、插入行等）调用此接口。
    """
    if not await _ensure_officecli():
        return JSONResponse(status_code=503, content={"installing": True, "detail": "OfficeCLI is being installed"})
    mgr = get_office_manager()

    docs_dir = _get_docs_dir(user.id, req.workspace)
    file_path = _safe_path(docs_dir, req.path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    if ext not in _PREVIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    batch_cmd = _build_batch_cmd(req)
    if batch_cmd is None:
        raise HTTPException(status_code=400, detail=f"Invalid operation or params: {req.operation}")

    logger.info("[QE-table] %s on %s/%s params=%s", req.operation, req.path, req.sheet, req.params)

    _backup_doc(file_path)

    try:
        # 用 batch 执行单条命令（一次 open/save 周期）
        result = await mgr.batch(str(file_path), [batch_cmd])

        if not result.success:
            return TableOpResponse(
                status="error",
                error=result.error or "Unknown error",
                message=f"操作失败: {req.operation}",
            )

        # 渲染新预览
        preview_result = await mgr.view_html(str(file_path))
        preview_html = _fix_html_newlines(preview_result.data) if preview_result.success else None

        return TableOpResponse(
            status="ok",
            preview_html=preview_html,
            message=f"✅ {req.operation} 成功",
        )
    except Exception as e:
        logger.exception("[QE-table] Error")
        raise HTTPException(status_code=500, detail=str(e))


# ── Quick Edit: PPT theme ─────────────────────────────────────────────


class ThemeEditRequest(BaseModel):
    """请求：修改 PPT 主题配色/字体。"""

    path: str
    workspace: str = ""
    props: dict[str, str]
    """主题属性：
    - accent1~accent6: 主题配色（十六进制如 4472C4）
    - headingFont: 标题字体
    - bodyFont: 正文字体
    - dk1/lt1/dk2/lt2: 基础色
    - hyperlink: 超链接色
    """


@router.post("/quick-edit/theme", response_model=QuickEditStyleResponse)
async def quick_edit_theme(
    req: ThemeEditRequest,
    user: User = Depends(get_current_user),
):
    """修改 PPT 主题颜色和字体方案。"""
    if not await _ensure_officecli():
        return JSONResponse(status_code=503, content={"installing": True, "detail": "OfficeCLI is being installed"})
    mgr = get_office_manager()

    docs_dir = _get_docs_dir(user.id, req.workspace)
    file_path = _safe_path(docs_dir, req.path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if file_path.suffix.lower() != ".pptx":
        raise HTTPException(status_code=400, detail="Theme editing is only supported for .pptx files")

    if not req.props:
        raise HTTPException(status_code=400, detail="No theme props provided")

    _backup_doc(file_path)

    logger.info("[QE-theme] %d prop(s) on %s", len(req.props), req.path)

    result = await mgr.set_props(str(file_path), "/theme", dict(req.props))

    results = [{
        "element": "/theme",
        "success": result.success,
        "error": result.error if not result.success else "",
    }]

    # 渲染新预览
    preview_result = await mgr.view_html(str(file_path))
    preview_html = _fix_html_newlines(preview_result.data) if preview_result.success else None

    return QuickEditStyleResponse(
        status="ok" if result.success else "error",
        preview_html=preview_html,
        results=results,
        message="主题已更新" if result.success else f"主题更新失败: {result.error}",
    )
