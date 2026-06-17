from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OfficeResult:
    """封装 OfficeCLI 命令的执行结果。"""

    success: bool
    data: Any = None
    error: str = ""
    raw_output: str = ""


# ── known locations to probe when officecli is not on PATH ──────────────
_PROBE_LOCATIONS = [
    "/usr/local/bin/officecli",
    "/opt/homebrew/bin/officecli",
    os.path.expanduser("~/.officecli/officecli"),
    os.path.expanduser("~/.local/bin/officecli"),
    "/usr/bin/officecli",
]


class OfficeManager:
    """OfficeCLI binary 管理器。

    职责：
    1. 检测系统是否安装了 OfficeCLI
    2. 提供类型安全的命令执行接口（异步 subprocess）
    3. 解析 JSON 输出
    4. 管理 resident mode 的长驻进程（预留给未来批量操作优化）
    """

    BINARY_NAME = "officecli"

    def __init__(self) -> None:
        self._binary_path: str | None = None
        self._available: bool = False
        self._version: str = ""

    # ── detection ────────────────────────────────────────────────────────

    async def detect(self) -> bool:
        """在系统上查找 OfficeCLI binary。

        依次检查：
        1. PATH 中的 ``officecli``
        2. 常见安装路径（_PROBE_LOCATIONS）

        返回 True 表示找到可用 binary。
        """
        # 1) PATH lookup
        path_in_path = shutil.which(self.BINARY_NAME)
        if path_in_path:
            return await self._set_binary(path_in_path)

        # 2) probe known locations
        for candidate in _PROBE_LOCATIONS:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return await self._set_binary(candidate)

        logger.info("OfficeCLI not found — office tools will be unavailable")
        return False

    async def _set_binary(self, path: str) -> bool:
        self._binary_path = path
        self._available = True
        try:
            result = await self._run_cmd([path, "--version"])
            self._version = result.strip()
        except Exception:
            self._version = "unknown"
        logger.info("OfficeCLI detected: %s (%s)", path, self._version)
        return True

    # ── properties ──────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._available

    @property
    def version(self) -> str:
        return self._version

    @property
    def binary_path(self) -> str | None:
        return self._binary_path

    # ── generic command execution ───────────────────────────────────────

    async def exec(self, *args: str, timeout: int = 60) -> OfficeResult:
        """执行任意 OfficeCLI 命令。

        Parameters
        ----------
        *args : str
            命令及其参数，例如 ``"view", "file.pptx", "--mode", "html"``
        timeout : int
            超时秒数（默认 60）

        Returns
        -------
        OfficeResult
            如果 binary 输出 JSON 格式（以 ``{`` 开头），自动解析。
        """
        cmd = [self._binary_path, *args] if self._available else []
        if not cmd:
            return OfficeResult(
                success=False,
                error=(
                    "OfficeCLI is not installed. "
                    "Install with: curl -fsSL https://raw.githubusercontent.com/"
                    "iOfficeAI/OfficeCLI/main/install.sh | bash"
                ),
            )
        return await self._exec_with_stdin(cmd, timeout=timeout)

    # ── high-level helpers ──────────────────────────────────────────────

    async def view_html(self, file_path: str) -> OfficeResult:
        """将文档渲染为 HTML 预览。"""
        return await self.exec("view", file_path, "html")

    async def view_text(
        self,
        file_path: str,
        max_lines: int = 200,
        sheet: str = "",
        cols: str = "",
        start: int = 0,
    ) -> OfficeResult:
        """读取文档的纯文本内容。"""
        args = ["view", file_path, "text", "--max-lines", str(max_lines)]
        if start > 0:
            args.extend(["--start", str(start)])
        if sheet:
            args.extend(["--sheet", sheet])
        if cols:
            args.extend(["--cols", cols])
        return await self.exec(*args)

    async def view_outline(self, file_path: str) -> OfficeResult:
        """查看文档大纲结构。"""
        return await self.exec("view", file_path, "outline")

    async def view_stats(self, file_path: str) -> OfficeResult:
        """查看文档统计信息。"""
        return await self.exec("view", file_path, "stats")

    async def create(self, file_path: str) -> OfficeResult:
        """创建空白文档（根据文件扩展名推断类型）。"""
        return await self.exec("create", file_path)

    async def set_props(
        self, file_path: str, element_path: str, props: dict[str, Any]
    ) -> OfficeResult:
        """修改文档中某元素的属性。

        Parameters
        ----------
        element_path : str
            元素路径，如 ``/slide[1]``, ``/slide[1]/shape[1]``,
            ``/sheet[1]/cell[A1]``
        props : dict
            要设置的键值对（text, font, size, color 等）
        """
        cmd = ["set", file_path, element_path]
        for k, v in props.items():
            cmd.extend(["--prop", f"{k}={v}"])
        return await self.exec(*cmd)

    async def add_element(
        self,
        file_path: str,
        parent_path: str,
        element_type: str,
        props: dict[str, Any] | None = None,
    ) -> OfficeResult:
        """在文档中添加子元素。

        Parameters
        ----------
        parent_path : str
            父元素路径，如 ``/``（根）, ``/slide[1]``, ``/body``
        element_type : str
            元素类型，如 ``slide``, ``shape``, ``table``, ``paragraph``,
            ``chart``, ``image``, ``sheet``, ``row``, ``cell``
        props : dict | None
            元素的属性。支持的定位键（不会传给 CLI --prop）：
            - ``index``: 插入位置（0-based）
            - ``after``: 在此路径的元素之后插入
            - ``before``: 在此路径的元素之前插入
            - ``data``: table 专用，二维数组 JSON（通过 stdin 传递）
        """
        cmd = [self._binary_path, "add", file_path, parent_path, "--type", element_type]

        # 分离定位参数和普通属性
        pass_props: dict[str, Any] = {}
        table_data: Any = None
        for k, v in (props or {}).items():
            if k == "index":
                cmd.extend(["--index", str(int(v))])
            elif k in ("after", "before"):
                cmd.extend([f"--{k}", str(v)])
            elif k == "data":
                table_data = v
            else:
                pass_props[k] = v

        for k, v in pass_props.items():
            cmd.extend(["--prop", f"{k}={v}"])

        # table 的 data 用 stdin 传递，避免命令行参数长度限制
        stdin_data: bytes | None = None
        if table_data is not None:
            stdin_data = json.dumps(table_data).encode("utf-8")

        return await self._exec_with_stdin(cmd, stdin_data)

    async def remove_element(self, file_path: str, element_path: str) -> OfficeResult:
        """删除文档中的元素。"""
        return await self.exec("remove", file_path, element_path)

    async def move_element(
        self, file_path: str, element_path: str, to_parent: str, index: int = -1
    ) -> OfficeResult:
        """移动元素到新的父节点下。"""
        cmd = ["move", file_path, element_path, "--to", to_parent]
        if index >= 0:
            cmd.extend(["--index", str(index)])
        return await self.exec(*cmd)

    async def get_element(
        self, file_path: str, element_path: str, depth: int = 1
    ) -> OfficeResult:
        """获取元素的 JSON 结构化信息。"""
        cmd = ["get", file_path, element_path, "--json"]
        if depth > 1:
            cmd.extend(["--depth", str(depth)])
        return await self.exec(*cmd)

    async def query(
        self, file_path: str, selector: str, max_results: int = 50
    ) -> OfficeResult:
        """使用选择器查询文档元素。

        Parameters
        ----------
        selector : str
            选择器表达式，如 ``"shape:contains(TODO)"``
        """
        cmd = ["query", file_path, selector]
        return await self.exec(*cmd)

    async def batch(
        self, file_path: str, commands: list[dict[str, Any]]
    ) -> OfficeResult:
        """在单次打开/保存周期内批量执行多个操作。"""
        payload = json.dumps(commands)
        return await self.exec("batch", file_path, "--commands", payload)

    async def help_for(self, fmt: str) -> OfficeResult:
        """获取指定格式的帮助参考（属性列表等）。"""
        return await self.exec("help", "--format", fmt)

    # ── internal ────────────────────────────────────────────────────────

    async def _exec_with_stdin(
        self, cmd: list[str], stdin_data: bytes | None = None, timeout: int = 60
    ) -> OfficeResult:
        """执行命令，可选通过 stdin 传递数据。"""
        if not self._available:
            return OfficeResult(
                success=False,
                error="OfficeCLI is not installed.",
            )

        logger.debug("officecli: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=timeout
            )
            stdout_decoded = stdout.decode("utf-8", errors="replace")
            stderr_decoded = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return OfficeResult(
                    success=False,
                    error=stderr_decoded or f"Exit code {proc.returncode}",
                    raw_output=stdout_decoded,
                )

            # 尝试 JSON 解析
            trimmed = stdout_decoded.strip()
            if trimmed.startswith("{"):
                try:
                    payload = json.loads(trimmed)
                    return OfficeResult(
                        success=payload.get("success", True),
                        data=payload.get("data", payload),
                        error=payload.get("error", ""),
                        raw_output=stdout_decoded,
                    )
                except json.JSONDecodeError:
                    pass

            return OfficeResult(success=True, data=stdout_decoded, raw_output=stdout_decoded)

        except TimeoutError:
            return OfficeResult(success=False, error=f"Command timed out ({timeout}s)")
        except FileNotFoundError:
            self._available = False
            return OfficeResult(success=False, error="OfficeCLI binary not found")
        except Exception as e:
            logger.exception("OfficeCLI exec failed")
            return OfficeResult(success=False, error=str(e))

    async def _run_cmd(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()


# ── global singleton ───────────────────────────────────────────────────

_manager: OfficeManager | None = None


def get_office_manager() -> OfficeManager:
    """获取全局 OfficeManager 单例。"""
    global _manager
    if _manager is None:
        _manager = OfficeManager()
    return _manager
