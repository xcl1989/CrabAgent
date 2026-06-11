from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from crabagent.core.agent.tools.registry import registry
from crabagent.core.event import AgentEvent, EventType
from crabagent.core.office.manager import get_office_manager

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────

_SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".pptx"}


def _resolve_path(file_path: str, context: Any = None) -> str:
    """将相对路径解析为工作区下的绝对路径。"""
    if os.path.isabs(file_path):
        return file_path
    if context and hasattr(context, "workspace") and context.workspace:
        return str(Path(context.workspace).resolve() / file_path)
    return file_path


def _resolve_path_or_current(file_path: str, context: Any = None) -> tuple[str | None, str | None]:
    """解析路径，如果 file_path 为空则尝试从 context 中取当前文档。

    Returns:
        (resolved_path, None) 成功
        (None, error_message) 失败
    """
    if file_path:
        return _resolve_path(file_path, context), None
    # file_path 为空 → 从 context metadata 中读 current_doc
    if context and context.metadata.get("current_doc"):
        doc = context.metadata["current_doc"]
        return _resolve_path(doc, context), None
    return None, "⚠️ 请指定文档路径，或先在左侧文件树中打开一个文档"


def _check_available() -> str | None:
    """如果 OfficeCLI 不可用则返回错误提示。"""
    mgr = get_office_manager()
    if not mgr.available:
        return (
            "❌ OfficeCLI is not installed.\n\n"
            "Install with one command:\n"
            "```bash\n"
            "curl -fsSL https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.sh | bash\n"
            "```\n"
            "Or download from: https://github.com/iOfficeAI/OfficeCLI/releases"
        )
    return None


def _check_extension(file_path: str) -> str | None:
    """检查文件扩展名是否受支持。"""
    ext = Path(file_path).suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
        return (
            f"Unsupported file format '{ext}'. "
            f"Supported formats: {supported}"
        )
    return None


async def _emit(context: Any, event_type: EventType, data: dict[str, Any]) -> None:
    """发射 SSE 事件（仅在 serve 模式下有 event_bus）。"""
    if context and hasattr(context, "event_bus") and context.event_bus:
        try:
            await context.event_bus.emit(AgentEvent(type=event_type, data=data))
        except Exception:
            logger.debug("Failed to emit office event", exc_info=True)


async def _render_and_emit_preview(
    file_path: str, resolved: str, context: Any
) -> None:
    """操作成功后渲染预览并发射。"""
    mgr = get_office_manager()
    preview = await mgr.view_html(resolved)
    if preview.success:
        await _emit(context, EventType.DOC_OP_PREVIEW, {
            "file": file_path,
            "html": preview.data,
        })
    else:
        logger.debug("Preview render skipped (not critical): %s", preview.error)


# ── tool: office_read ──────────────────────────────────────────────────


@registry.register(
    name="office_read",
    description="读取 Office 文档的内容。支持 .docx(Word)、.xlsx(Excel)、.pptx(PowerPoint)。"
    "返回纯文本内容或结构化 JSON，方便 AI 分析文档数据。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文档路径（绝对路径，或相对于当前工作区的路径）。留空则自动使用当前打开的文档。",
            },
            "mode": {
                "type": "string",
                "enum": ["text", "outline", "stats"],
                "description": "读取模式：text-全文文本, outline-大纲结构, stats-统计信息",
                "default": "text",
            },
            "sheet": {
                "type": "string",
                "description": "（Excel 专用）工作表名称，如 'Sheet1'，留空则读取所有工作表",
            },
            "max_lines": {
                "type": "integer",
                "description": "最大返回行数",
                "default": 200,
            },
            "offset": {
                "type": "integer",
                "description": "起始行/段落编号（从1开始）。用于跳过文档前段内容，直接读取中后部分。",
                "default": 0,
            },
        },
        "required": [],
    },
)
async def office_read(
    file_path: str = "",
    mode: str = "text",
    sheet: str = "",
    max_lines: int = 200,
    offset: int = 0,
    context: Any = None,
) -> str:
    """读取 Office 文档内容。"""
    err = _check_available()
    if err:
        return err

    resolved, err_msg = _resolve_path_or_current(file_path, context)
    if err_msg:
        return err_msg

    err_ext = _check_extension(resolved)
    if err_ext:
        return err_ext

    if not os.path.isfile(resolved):
        return f"File not found: {resolved}"

    mgr = get_office_manager()

    if mode == "outline":
        result = await mgr.view_outline(resolved)
    elif mode == "stats":
        result = await mgr.view_stats(resolved)
    else:
        result = await mgr.view_text(
            resolved, max_lines=max_lines, sheet=sheet, start=offset
        )

    if not result.success:
        return f"读取失败: {result.error}"

    content = result.data or ""
    summary = f"📄 已读取 {Path(file_path).name} ({mode} 模式, {len(str(content))} 字符)\n\n"
    return summary + str(content)


# ── tool: office_create ────────────────────────────────────────────────


@registry.register(
    name="office_create",
    description="创建新的 Office 文档。支持 .docx(Word)、.xlsx(Excel)、.pptx(PowerPoint)。"
    "创建后返回文件路径，可继续用 office_edit 添加内容。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要创建的文档路径（绝对路径，或相对于工作区的路径）。留空则自动使用当前打开的文档。",
            },
        },
        "required": [],
    },
)
async def office_create(file_path: str = "", context: Any = None) -> str:
    """创建新的 Office 文档。"""
    err = _check_available()
    if err:
        return err

    resolved, err_msg = _resolve_path_or_current(file_path, context)
    if err_msg:
        return err_msg

    err_ext = _check_extension(resolved)
    if err_ext:
        return err_ext

    # 如果文件已存在，先确认
    if os.path.isfile(resolved):
        return (
            f"File already exists: {file_path}\n"
            f"Use office_edit to modify it, or delete it first."
        )

    # 确保父目录存在
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)

    await _emit(context, EventType.DOC_OP_START, {
        "file": file_path,
        "operation": "create",
    })

    mgr = get_office_manager()
    result = await mgr.create(resolved)

    if result.success:
        await _emit(context, EventType.DOC_OP_DONE, {
            "file": file_path,
            "status": "ok",
            "message": f"✅ 文档已创建: {file_path}",
        })
        # 尝试渲染预览
        preview = await mgr.view_html(resolved)
        if preview.success:
            await _emit(context, EventType.DOC_OP_PREVIEW, {
                "file": file_path,
                "html": preview.data,
            })
        return f"✅ 文档已创建: {file_path}\n文件大小: {os.path.getsize(resolved)} bytes"
    else:
        await _emit(context, EventType.DOC_OP_DONE, {
            "file": file_path,
            "status": "error",
            "message": f"创建失败: {result.error}",
        })
        return f"创建失败: {result.error}"


# ── tool: office_edit ──────────────────────────────────────────────────


_EDIT_DESCRIPTIONS = {
    "set": "✏️ set",
    "add": "➕ add",
    "remove": "🗑️ remove",
    "move": "↗️ move",
}


def _describe_op(
    command: str, element_path: str, props: dict[str, Any] | None
) -> str:
    icon = _EDIT_DESCRIPTIONS.get(command, "📄")
    text = ""
    if props:
        text = props.get("text", props.get("title", ""))
        if isinstance(text, str) and len(text) > 60:
            text = text[:60] + "…"
    desc = f"{icon} {command} {element_path}"
    if text:
        desc += f' "{text}"'
    return desc


@registry.register(
    name="office_edit",
    description="编辑 Office 文档中的元素。支持修改文本/样式（set）、添加元素（add）、"
    "删除元素（remove）、移动元素（move）。适用于 Word/Excel/PowerPoint。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文档路径。留空则自动使用当前打开的文档。",
            },
            "command": {
                "type": "string",
                "enum": ["set", "add", "remove", "move"],
                "description": "操作类型：\n"
                "- set: 修改已有元素的属性（文本、字体、颜色、大小等）\n"
                "- add: 添加新元素（幻灯片、形状、表格、图表等）\n"
                "- remove: 删除元素\n"
                "- move: 移动元素到新位置",
            },
            "element_path": {
                "type": "string",
                "description": "元素路径。常用路径：\n"
                "- / → 文档根\n"
                "- /slide[1] → 第1张幻灯片\n"
                "- /slide[1]/shape[1] → 第1张幻灯片的第1个形状\n"
                "- /sheet[1]/cell[A1] → Excel 第1个工作表的 A1 单元格\n"
                "- /body/p[1] → Word 第1段落",
            },
            "props": {
                "type": "object",
                "description": "要设置的属性键值对。常用属性：\n"
                "- text: 文本内容\n"
                "- title: 幻灯片标题\n"
                "- font: 字体名称\n"
                "- size: 字号（pt）\n"
                "- color: 颜色（十六进制 #FF0000 或命名色）\n"
                "- background: 背景色\n"
                "- width, height: 尺寸\n"
                "- x, y: 位置",
            },
            "element_type": {
                "type": "string",
                "description": "（add 操作专用）要添加的元素类型：\n"
                "- slide: 幻灯片（PPT）\n"
                "- shape: 形状/文本框\n"
                "- table: 表格\n"
                "- chart: 图表\n"
                "- image: 图片\n"
                "- sheet: 工作表（Excel）\n"
                "- paragraph: 段落（Word）\n"
                "- row: 行（表格）\n"
                "- cell: 单元格（表格）",
            },
        },
        "required": ["command"],
    },
)
async def office_edit(
    file_path: str = "",
    command: str = "",
    element_path: str = "",
    props: dict[str, Any] | None = None,
    element_type: str = "",
    context: Any = None,
) -> str:
    """编辑 Office 文档中的元素。"""
    err = _check_available()
    if err:
        return err

    resolved, err_msg = _resolve_path_or_current(file_path, context)
    if err_msg:
        return err_msg

    err_ext = _check_extension(resolved)
    if err_ext:
        return err_ext

    if not os.path.isfile(resolved):
        return f"File not found: {resolved}"

    mgr = get_office_manager()
    props = props or {}

    # 发射进度事件
    desc = _describe_op(command, element_path, props)
    await _emit(context, EventType.DOC_OP_DELTA, {
        "file": file_path,
        "message": desc,
    })

    # 执行操作
    if command == "set":
        result = await mgr.set_props(resolved, element_path, props)
    elif command == "add":
        if not element_type:
            return "add 操作需要指定 element_type（如 slide、shape、table）"
        result = await mgr.add_element(resolved, element_path, element_type, props)
    elif command == "remove":
        result = await mgr.remove_element(resolved, element_path)
    elif command == "move":
        to_parent = props.get("to", "")
        index = props.get("index", -1)
        if not to_parent:
            return "move 操作需要指定目标路径（props.to）"
        result = await mgr.move_element(
            resolved, element_path, to_parent, int(index)
        )
    else:
        return f"不支持的命令: {command}"

    if result.success:
        # 渲染预览
        await _render_and_emit_preview(file_path, resolved, context)
        return f"✅ {_describe_op(command, element_path, props)}"
    else:
        return f"操作失败: {result.error}"


# ── tool: office_query ─────────────────────────────────────────────────


@registry.register(
    name="office_query",
    description="查询 Office 文档中的元素。支持按路径获取结构化 JSON，"
    "或使用选择器按条件查找元素。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文档路径。留空则自动使用当前打开的文档。",
            },
            "path_or_selector": {
                "type": "string",
                "description": "元素路径（如 /slide[1]/shape[1]）或选择器表达式。"
                "选择器示例：\n"
                '- "shape:contains(TODO)" → 查找含 TODO 的 shape\n'
                '- "text:contains(报告)" → 查找含"报告"的文本\n'
                '- "table:*" → 查找所有表格',
            },
            "mode": {
                "type": "string",
                "enum": ["path", "selector"],
                "description": "查询模式：path-按路径获取, selector-按选择器搜索",
                "default": "path",
            },
            "depth": {
                "type": "integer",
                "description": "（path 模式）递归深度",
                "default": 1,
            },
        },
        "required": ["path_or_selector"],
    },
)
async def office_query(
    file_path: str = "",
    path_or_selector: str = "",
    mode: str = "path",
    depth: int = 1,
    context: Any = None,
) -> str:
    """查询文档元素。"""
    err = _check_available()
    if err:
        return err

    resolved, err_msg = _resolve_path_or_current(file_path, context)
    if err_msg:
        return err_msg

    err_ext = _check_extension(resolved)
    if err_ext:
        return err_ext

    if not os.path.isfile(resolved):
        return f"File not found: {resolved}"

    mgr = get_office_manager()

    if mode == "selector":
        result = await mgr.query(resolved, path_or_selector)
    else:
        result = await mgr.get_element(resolved, path_or_selector, depth=depth)

    if not result.success:
        return f"查询失败: {result.error}"

    data = result.data
    if isinstance(data, (dict, list)):
        import json as _json

        output = _json.dumps(data, ensure_ascii=False, indent=2)
        # 截断过长的输出，避免返回几十万字符
        max_chars = 50_000
        if len(output) > max_chars:
            output = (
                output[:max_chars]
                + "\n\n... (输出已截断，共 "
                + str(len(output))
                + " 字符。请使用更精确的路径或增加 depth 来缩小范围)"
            )
        return output
    return str(data)


# ── tool: office_render ────────────────────────────────────────────────


@registry.register(
    name="office_render",
    description="将 Office 文档渲染为 HTML 预览。返回的 HTML 可直接在浏览器中显示，"
    "让用户看到文档的视觉呈现效果。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文档路径。留空则自动使用当前打开的文档。",
            },
        },
        "required": [],
    },
)
async def office_render(file_path: str = "", context: Any = None) -> str:
    """渲染文档为 HTML 预览。"""
    err = _check_available()
    if err:
        return err

    resolved, err_msg = _resolve_path_or_current(file_path, context)
    if err_msg:
        return err_msg

    err_ext = _check_extension(resolved)
    if err_ext:
        return err_ext

    if not os.path.isfile(resolved):
        return f"File not found: {resolved}"

    mgr = get_office_manager()
    result = await mgr.view_html(resolved)

    if not result.success:
        return f"渲染失败: {result.error}"

    html = result.data or ""

    await _emit(context, EventType.DOC_OP_PREVIEW, {
        "file": file_path,
        "html": html,
    })

    return html
