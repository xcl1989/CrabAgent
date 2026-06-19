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


async def _ensure_available() -> str | None:
    """确保 OfficeCLI 可用，必要时自动检测+自动安装。返回错误信息或 None。"""
    mgr = get_office_manager()
    if not mgr.available:
        # 先尝试检测（可能已安装在非标准路径）
        if await mgr.detect():
            return None
        # 自动下载安装
        logger.info("OfficeCLI not found — attempting auto-install…")
        if await mgr.install():
            logger.info("OfficeCLI auto-install succeeded")
            return None
        # 安装失败，显示安装指引
        from crabagent.core.office.manager import _INSTALL_HINT
        return _INSTALL_HINT
    return None


async def _collect_formulas(mgr: Any, file_path: str, sheet: str = "") -> str:
    """收集 xlsx 中的公式单元格，返回可读的公式摘要。

    使用 query cell 选择器查找含公式的单元格，然后逐个获取详情。
    """
    # 用 query 查找所有有 formula 的单元格
    result = await mgr.query(file_path, "cell[formula]")
    if not result.success or not result.data:
        return ""

    cells = result.data if isinstance(result.data, list) else result.data.get("results", [])
    if not cells:
        # query 可能返回 dict 格式
        if isinstance(result.data, dict):
            cells = result.data.get("results", [])

    if not cells:
        return ""

    lines: list[str] = []
    for cell_node in cells[:50]:  # 限制最多 50 个，避免输出过长
        if isinstance(cell_node, dict):
            path = cell_node.get("path", "")
            fmt = cell_node.get("format", {})
            if isinstance(fmt, dict):
                formula = fmt.get("formula", "")
                cached = fmt.get("cachedValue", "")
                computed = fmt.get("computedValue", "")
                display = computed or cached or "?"
                lines.append(f"{path}: ={formula}  →  {display}")

    return "\n".join(lines) if lines else ""


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
    err = await _ensure_available()
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

    # 对 xlsx 文件，在 text 模式下追加公式信息
    if mode == "text" and resolved.endswith(".xlsx"):
        try:
            formula_info = await _collect_formulas(mgr, resolved, sheet)
            if formula_info:
                content += "\n\n--- 公式单元格 ---\n" + formula_info
        except Exception:
            logger.debug("Formula collection failed", exc_info=True)

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
    err = await _ensure_available()
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
                "enum": ["set", "add", "remove", "move", "swap"],
                "description": "操作类型：\n"
                "- set: 修改已有元素的属性（文本、字体、颜色、大小、公式、合并等）\n"
                "- add: 添加新元素（幻灯片、形状、表格、行、列、单元格等）\n"
                "- remove: 删除元素\n"
                "- move: 移动元素到新位置\n"
                "- swap: 交换两个元素的位置",
            },
            "element_path": {
                "type": "string",
                "description": "元素路径。常用路径：\n"
                "- / → 文档根\n"
                "- /slide[1] → 第1张幻灯片\n"
                "- /slide[1]/shape[1] → 第1张幻灯片的第1个形状\n"
                "- /Sheet1/A1 → Excel 的 A1 单元格（注意：Sheet名区分大小写，用字母列号）\n"
                "- /Sheet1/A1:C3 → Excel 的范围（用于合并/批量格式化）\n"
                "- /Sheet1/row[3] → Excel 第3行（用于设置行高/删除行）\n"
                "- /Sheet1/col[A] → Excel A列（用于设置列宽/删除列）\n"
                "- /theme → PPT 主题（颜色/字体方案）\n"
                "- /slidemaster[1] → PPT 母版\n"
                "- /body/p[1] → Word 第1段落\n"
                "- /body/tbl[1]/tr[2]/tc[1] → Word 表格第2行第1列单元格\n"
                "- /slide[1]/table[1]/tr[2]/tc[1] → PPT 表格第2行第1列单元格\n\n"
                "⚠️ Excel 注意：新建的空白工作表中没有预置的单元格。\n"
                "   先使用 add 命令添加单元格（如 add → parent=/Sheet1, type=cell），\n"
                "   然后再用 set 修改其内容。\n"
                "   add 会自动创建行和单元格，路径形如 /Sheet1/A1、/Sheet1/B2 等。",
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
                "- x, y: 位置\n\n"
                "Excel 专用属性：\n"
                "- formula: 单元格公式（不含=前缀），如 SUM(A1:A10)\n"
                "- merge: 合并单元格，传范围如 A1:C3 或 true/false（用于 range 路径）\n"
                "- numberformat: 数字格式，如 #,##0.00 或 yyyy-mm-dd\n"
                "- fill: 单元格背景色\n"
                "- border.all: 边框样式，如 'single;1pt;FF0000'\n"
                "- bold/italic/underline/strike: 字体样式\n"
                "- alignment.horizontal: 对齐（left/center/right）\n"
                "- shift: 插入时位移（right/down）\n\n"
                "Word 表格专用属性：\n"
                "- colspan: 水平合并列数\n"
                "- vmerge: 垂直合并（restart 标记起始，continue 标记后续）\n"
                "- valign: 垂直对齐（top/center/bottom）\n\n"
                "PPT 专用属性：\n"
                "- layout: 幻灯片布局名（如 'Title Slide'、'Title and Content'、'Blank'）\n"
                "- merge.right: 表格水平合并列数\n"
                "- transition: 幻灯片切换效果（fade/push/wipe/morph）\n\n"
                "PPT 主题属性（路径 /theme）：\n"
                "- accent1~accent6: 主题配色\n"
                "- headingFont: 标题字体 / bodyFont: 正文字体\n\n"
                "表格创建属性（add table）：\n"
                "- data: 表格数据。支持两种格式：\n"
                "  - JSON 二维数组（推荐）：[['A','B'],['1','2']]\n"
                "  - CSV 字符串（兼容）：'A,B;1,2'\n"
                "- style: 表格样式（medium1~4, light1~3, dark1~2）\n"
                "- headerFill/bodyFill: 表头/正文背景色\n"
                "- border.all/border.horizontal/border.vertical: 边框",
            },
            "element_type": {
                "type": "string",
                "description": "（add 操作专用）要添加的元素类型：\n"
                "- slide: 幻灯片（PPT）— 支持 layout/title/text 属性\n"
                "- shape: 形状/文本框\n"
                "- table: 表格— 支持 data/style/headerFill 属性\n"
                "- chart: 图表\n"
                "- image: 图片\n"
                "- sheet: 工作表（Excel）\n"
                "- row: 行（Excel: add 到 /SheetName — 支持 --after/--before 插入到指定位置）\n"
                "- column: 列（Excel: add 到 /SheetName — --prop name=C 指定列字母）\n"
                "- cell: 单元格（Excel: add 到 /SheetName — --prop ref=B2 指定位置）\n"
                "- paragraph: 段落（Word）\n"
                "- placeholder: PPT 占位符（--prop phType=title/body）",
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
    err = await _ensure_available()
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
        "element_path": element_path,
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
    elif command == "swap":
        path2 = props.get("with", "")
        if not path2:
            return "swap 操作需要指定 props.with（第二个元素的路径）"
        result = await mgr.exec("swap", resolved, element_path, path2)
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
    err = await _ensure_available()
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
    err = await _ensure_available()
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
