"""CrabAgent Dual-Panel TUI — prompt_toolkit Application with Rich rendering.

Layout:
  ┌──────────────────────────────────────┐
  │  Output panel (Rich → ANSI segments) │
  │  Streaming text, tool calls, sub-    │
  │  agent status, thinking, etc.        │
  ├──────────────────────────────────────┤
  │  Status bar (model, msgs, tokens)    │
  │  > user input (always active)        │
  └──────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from collections import deque

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import ANSI, FormattedText, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import CompletionsMenu
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.styles import Style as PtStyle
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from crabagent import __version__
from crabagent.cli.tui import SLASH_COMMANDS, TuiSession
from crabagent.core.agent.loop import run_agent
from crabagent.core.event import AgentEvent, EventType

_MAX_SEGMENTS = 2000

_PT_STYLE = PtStyle.from_dict(
    {
        "status-bar": "bg:#161b22 #8b949e",
        "status-running": "bg:#161b22 #58a6ff",
        "status-queue": "bg:#161b22 #f0883e",
        "status-agent": "bg:#161b22 #7ee787",
        "separator": "#30363d",
        "prompt": "bold",
        "selected": "reverse",
        "popup": "bg:#1c2333 #e6edf3",
        "popup-title": "bg:#1c2333 bold #58a6ff",
        "popup-selected": "bg:#264f78 #e6edf3",
        "popup-border": "bg:#1c2333 #30363d",
    }
)


class _SelectionPopup:
    """Generic popup selector for dual-panel TUI."""

    def __init__(self):
        self.visible = False
        self.title = ""
        self.items: list[tuple[str, str]] = []
        self._selected_idx = 0
        self._on_select = None
        self._on_cancel = None
        self._app: Application | None = None
        self.control = FormattedTextControl(
            self._get_ft,
            focusable=False,
        )
        self.window = Window(
            content=self.control,
            height=Dimension(min=3, max=15),
            width=Dimension(min=20, max=60),
            style="class:popup",
        )

    def show(self, title, items, on_select, on_cancel=None):
        self.title = title
        self.items = items
        self._selected_idx = 0
        self._on_select = on_select
        self._on_cancel = on_cancel
        self.visible = True
        if self._app:
            self._app.invalidate()

    def close(self):
        self.visible = False
        self.items = []
        self._on_select = None
        self._on_cancel = None
        if self._app:
            self._app.invalidate()

    def handle_key(self, key: str) -> bool:
        if not self.visible:
            return False
        if key == "up":
            self._selected_idx = max(0, self._selected_idx - 1)
            if self._app:
                self._app.invalidate()
            return True
        elif key == "down":
            self._selected_idx = min(len(self.items) - 1, self._selected_idx + 1)
            if self._app:
                self._app.invalidate()
            return True
        elif key == "enter":
            if self._selected_idx < len(self.items):
                value = self.items[self._selected_idx][0]
                cb = self._on_select
                self.visible = False
                self.items = []
                self._on_select = None
                if cb:
                    asyncio.ensure_future(cb(value))
            return True
        elif key == "escape":
            cb = self._on_cancel
            self.visible = False
            self.items = []
            self._on_select = None
            self._on_cancel = None
            if cb:
                cb()
            if self._app:
                self._app.invalidate()
            return True
        return False

    def _get_ft(self):
        if not self.visible or not self.items:
            return FormattedText([("", "")])
        result = []
        result.append(("class:popup-title", f" {self.title}\n"))
        for i, (_, display) in enumerate(self.items):
            if i == self._selected_idx:
                result.append(("class:popup-selected", f" › {display}\n"))
            else:
                result.append(("class:popup", f"   {display}\n"))
        result.append(("class:popup-border", "─" * 30))
        return FormattedText(result)


_DIM_RE = re.compile(r"\x1b\[(\d+(?:;\d+)*)m")


def _fix_dim_to_gray(ansi: str) -> str:
    def _replace(m):
        codes = m.group(1).split(";")
        if "2" not in codes:
            return m.group(0)
        new_codes = [c for c in codes if c != "2"]
        new_codes += ["38", "5", "102"]
        return "\x1b[" + ";".join(new_codes) + "m"

    return _DIM_RE.sub(_replace, ansi)


def _r2a_static(console: Console, *rich_objects, **kwargs) -> str:
    with console.capture() as cap:
        console.print(*rich_objects, **kwargs)
    return _fix_dim_to_gray(cap.get().rstrip("\n"))


def _md2a_static(console: Console, text: str) -> str:
    if not text.strip():
        return ""
    return _r2a_static(console, Markdown(text))


class _CapturingConsole(Console):
    """Console that captures print output to the dual-panel TUI output buffer."""

    def __init__(self, tui, **kwargs):
        super().__init__(**kwargs)
        self._tui = tui

    def print(self, *args, **kwargs):
        with self.capture() as cap:
            super().print(*args, **kwargs)
        text = _fix_dim_to_gray(cap.get().rstrip("\n"))
        if text:
            self._tui._ansi_segments.append(text)
            self._tui._cache_dirty = True


_MOUSE_THROTTLE_SEC = 1 / 60


class DualPanelTui(TuiSession):
    def __init__(self, args):
        super().__init__(args)
        self._app: Application | None = None
        self._input_buffer = Buffer(
            multiline=False,
            completer=WordCompleter(SLASH_COMMANDS + ["/runs"], ignore_case=True, sentence=True),
            complete_while_typing=True,
        )
        self._ansi_segments: deque[str] = deque(maxlen=_MAX_SEGMENTS)
        self._cache_dirty = True
        self._agent_task: asyncio.Task | None = None
        self._thinking_active = False
        self._thinking_seg_idx: int | None = None
        tw = max(80, os.get_terminal_size().columns - 2) if os.isatty(1) else 80
        self._render_console = Console(force_terminal=True, width=tw, color_system="truecolor")
        self._abort_flag = False
        self._pending_calls: dict[str, tuple] = {}
        self._buffered_tool_pairs: list[tuple] = []
        self._auto_scroll = True
        self._scroll_y = 0
        self._output_line_count = 0
        self._output_window: Window | None = None

        self._sel_frag_start: int | None = None
        self._sel_frag_end: int | None = None
        self._sel_dragging = False
        self._sel_dirty = True
        self._last_mouse_time: float = 0.0

        self._output_plain_text = ""
        self._split_plain: list[str] = []

        self._cached_width = tw
        self._cached_seg_count = 0
        self._cached_fragments: list[tuple[str, str]] = []
        self._cached_merged: list[tuple[str, str]] = []
        self._cached_handlers: list = []
        self._cached_line_count = 0
        self._rendered_cache: FormattedText = FormattedText([("", "")])

        self._render_queue: asyncio.Queue = asyncio.Queue()
        self._render_worker_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None

        self._copy_msg = ""
        self._copy_msg_until = 0.0

        self._selection_popup = _SelectionPopup()

    def _r2a(self, *rich_objects, **kwargs) -> str:
        return _r2a_static(self._render_console, *rich_objects, **kwargs)

    async def _r2a_async(self, *rich_objects, **kwargs) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _r2a_static, self._render_console, *rich_objects, **kwargs)

    def _md2a(self, text: str) -> str:
        return _md2a_static(self._render_console, text)

    async def _md2a_async(self, text: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _md2a_static, self._render_console, text)

    def _append_ansi(self, ansi: str):
        if ansi:
            self._ansi_segments.append(ansi)
            self._cache_dirty = True

    def _append_md(self, md_text: str):
        ansi = self._md2a(md_text)
        if ansi:
            self._ansi_segments.append(ansi)
            self._cache_dirty = True

    def _append_rich(self, *rich_objects, **kwargs):
        ansi = self._r2a(*rich_objects, **kwargs)
        if ansi:
            self._ansi_segments.append(ansi)
            self._cache_dirty = True

    def _append_dim(self, text: str):
        self._append_rich(Text(text, style="dim"))

    def _invalidate(self):
        self._cache_dirty = True
        self._sel_dirty = True
        if self._app:
            self._app.invalidate()

    def _get_output_cursor_pos(self):
        max_y = max(0, self._output_line_count - 1)
        if self._auto_scroll and self._output_line_count > 0:
            return Point(x=0, y=max_y)
        return Point(x=0, y=min(self._scroll_y, max_y))

    def _get_vertical_scroll_cb(self, window):
        ri = window.render_info
        wh = ri.window_height if ri else 20
        max_scroll = max(0, self._output_line_count - wh)
        if self._auto_scroll:
            return max_scroll
        return min(self._scroll_y, max_scroll)

    async def run(self):
        await self._initialize()
        if not self.agent_ctx:
            return

        self._full_tool_registry = self.agent_ctx.tool_registry
        self._full_model = self.agent_ctx.model

        self.console = _CapturingConsole(
            self,
            force_terminal=True,
            width=self._render_console.width,
            color_system="truecolor",
        )

        self.agent_ctx.event_bus.subscribe(self._on_agent_event)

        self._append_md(f"**CrabAgent v{__version__}**\n\n  workspace: `{self.agent_ctx.workspace}`\n")

        app = self._build_application()
        self._app = app
        self._selection_popup._app = app

        self._render_worker_task = asyncio.create_task(self._render_worker())
        self._flush_task = asyncio.create_task(self._periodic_stream_flush())
        try:
            await app.run_async()
        except KeyboardInterrupt:
            pass
        finally:
            if self._render_worker_task:
                self._render_worker_task.cancel()
            if self._flush_task:
                self._flush_task.cancel()
            await self._cleanup()

    def _build_application(self) -> Application:
        kb = KeyBindings()
        buf = self._input_buffer
        popup = self._selection_popup
        tui = self

        @kb.add("up")
        def _on_popup_up(event):
            if popup.handle_key("up"):
                return

        @kb.add("down")
        def _on_popup_down(event):
            if popup.handle_key("down"):
                return

        @kb.add("escape")
        def _on_popup_escape(event):
            if popup.handle_key("escape"):
                return

        @kb.add("enter")
        def _on_enter(event):
            if popup.handle_key("enter"):
                return
            text = buf.text.strip()
            buf.text = ""
            if not text:
                return
            if text in ("/exit", "/quit"):
                event.app.exit()
                return
            if text == "/abort":
                if self._agent_running and self._agent_task and not self._agent_task.done():
                    self._agent_task.cancel()
                    self._append_dim("[aborted by user]")
                else:
                    self._append_dim("No agent running.")
                event.app.invalidate()
                return
            if self._agent_running:
                if len(self._pending_inputs) >= 5:
                    self._append_dim("Queue full (5 max)")
                else:
                    self._pending_inputs.append(text)
                event.app.invalidate()
                return
            asyncio.ensure_future(self._handle_input(text))
            event.app.invalidate()

        @kb.add("c-c")
        def _on_ctrl_c(event):
            if self._agent_running and self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
                self._append_dim("[aborted by user]")
                event.app.invalidate()
            else:
                event.app.exit()

        @kb.add("c-d")
        def _on_ctrl_d(event):
            event.app.exit()

        @kb.add("pageup")
        def _on_pageup(event):
            if tui._auto_scroll:
                tui._auto_scroll = False
                ri = tui._output_window.render_info if tui._output_window else None
                tui._scroll_y = ri.vertical_scroll if ri else 0
            try:
                rows = max(5, os.get_terminal_size().lines - 4)
            except Exception:
                rows = 20
            tui._scroll_y = max(0, tui._scroll_y - rows)
            event.app.invalidate()

        @kb.add("pagedown")
        def _on_pagedown(event):
            if tui._auto_scroll:
                tui._auto_scroll = False
                ri = tui._output_window.render_info if tui._output_window else None
                tui._scroll_y = ri.vertical_scroll if ri else 0
            try:
                rows = max(5, os.get_terminal_size().lines - 4)
            except Exception:
                rows = 20
            tui._scroll_y += rows
            ri = tui._output_window.render_info if tui._output_window else None
            wh = ri.window_height if ri else 20
            max_y = max(0, tui._output_line_count - wh)
            if tui._scroll_y >= max_y:
                tui._scroll_y = max_y
                tui._auto_scroll = True
            event.app.invalidate()

        @kb.add("home")
        def _on_home(event):
            tui._auto_scroll = False
            tui._scroll_y = 0
            event.app.invalidate()

        @kb.add("end")
        def _on_end(event):
            tui._auto_scroll = True
            event.app.invalidate()

        output_ctrl = FormattedTextControl(
            text=tui._get_output_ft,
            focusable=False,
            get_cursor_position=tui._get_output_cursor_pos,
        )
        status_ctrl = FormattedTextControl(
            text=tui._get_status_ft,
            focusable=False,
        )

        tui._output_window = Window(
            content=output_ctrl,
            wrap_lines=False,
            height=Dimension(min=3, weight=1),
            get_vertical_scroll=tui._get_vertical_scroll_cb,
        )

        from prompt_toolkit.filters import Condition
        from prompt_toolkit.layout import ConditionalContainer

        popup_visible = Condition(lambda: tui._selection_popup.visible)

        root = FloatContainer(
            content=HSplit(
                [
                    tui._output_window,
                    Window(height=1, char="─", style="class:separator"),
                    Window(content=status_ctrl, height=1, style="class:status-bar"),
                    Window(
                        content=BufferControl(buffer=buf, focus_on_click=True),
                        wrap_lines=True,
                        dont_extend_height=True,
                        height=Dimension(min=1, max=6),
                        get_line_prefix=lambda li, wa: FormattedText([("class:prompt", "> ")]),
                    ),
                ]
            ),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=10, scroll_offset=1),
                ),
                Float(
                    left=2,
                    bottom=3,
                    content=ConditionalContainer(
                        content=tui._selection_popup.window,
                        filter=popup_visible,
                    ),
                ),
            ],
        )

        return Application(
            layout=Layout(root),
            key_bindings=kb,
            style=_PT_STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.15,
        )

    def _get_output_ft(self):
        try:
            current_width = os.get_terminal_size().columns
        except Exception:
            current_width = self._cached_width

        width_changed = current_width != self._cached_width
        if width_changed:
            self._cached_width = max(80, current_width)
            self._render_console = Console(force_terminal=True, width=self._cached_width, color_system="truecolor")
            self._cached_seg_count = 0
            self._cached_fragments.clear()
            self._cache_dirty = True

        current_len = len(self._ansi_segments)

        if current_len < self._cached_seg_count:
            self._cached_seg_count = 0
            self._cached_fragments.clear()
            self._cache_dirty = True

        if self._cache_dirty:
            if self._cached_seg_count == 0 or self._cached_seg_count == current_len:
                self._cached_fragments = []
                self._cached_line_count = 1
                for idx, ansi_text in enumerate(self._ansi_segments):
                    if idx > 0:
                        self._cached_fragments.append(("", "\n"))
                        self._cached_line_count += 1
                    raw_ft = to_formatted_text(ANSI(ansi_text))
                    wrapped = self._wrap_ft(raw_ft, self._cached_width)
                    self._cached_line_count += sum(t.count("\n") for _, t in wrapped)
                    self._cached_fragments.extend(wrapped)
            else:
                while self._cached_seg_count < current_len:
                    idx = self._cached_seg_count
                    ansi_text = self._ansi_segments[idx]
                    if idx > 0:
                        self._cached_fragments.append(("", "\n"))
                        self._cached_line_count += 1
                    raw_ft = to_formatted_text(ANSI(ansi_text))
                    wrapped = self._wrap_ft(raw_ft, self._cached_width)
                    self._cached_line_count += sum(t.count("\n") for _, t in wrapped)
                    self._cached_fragments.extend(wrapped)
                    self._cached_seg_count += 1
            self._cached_seg_count = current_len
            self._cache_dirty = False
            self._rebuild_merged_cache()
            self._cached_line_count = 1
            for _, text in self._cached_merged:
                self._cached_line_count += text.count("\n")
            self._output_line_count = self._cached_line_count
            self._sel_dirty = True

        if not self._sel_dirty:
            return self._rendered_cache

        result = self._build_ft_with_selection()
        self._sel_dirty = False
        self._rendered_cache = result
        return result

    def _rebuild_merged_cache(self):
        merged = []
        for style, text in self._cached_fragments:
            if text == "\n":
                if merged:
                    prev_s, prev_t = merged[-1]
                    merged[-1] = (prev_s, prev_t.rstrip() + "\n")
                else:
                    merged.append((style, "\n"))
            else:
                if merged and merged[-1][0] == style:
                    prev_s, prev_t = merged[-1]
                    merged[-1] = (prev_s, prev_t + text)
                else:
                    merged.append((style, text))
        self._cached_merged = merged
        self._split_plain = [text for _, text in merged]
        self._cached_handlers = [self._make_frag_handler(idx) for idx in range(len(merged))]

    @staticmethod
    def _wrap_ft(ft, width):
        result = []
        col = 0
        for style, text in ft:
            if text == "\n":
                result.append((style, text))
                col = 0
                continue
            i = 0
            while i < len(text):
                if col >= width:
                    result.append(("", "\n"))
                    col = 0
                run_start = i
                run_col = col
                while i < len(text) and run_col < width:
                    ch = text[i]
                    cw = 2 if ord(ch) > 0x1100 else 1
                    if run_col + cw > width:
                        break
                    run_col += cw
                    i += 1
                if i > run_start:
                    result.append((style, text[run_start:i]))
                    col = run_col
                elif col > 0:
                    result.append(("", "\n"))
                    col = 0
                else:
                    result.append((style, text[i]))
                    i += 1
                    col = 0
        return result

    def _build_ft_with_selection(self):
        sel_start = self._sel_frag_start
        sel_end = self._sel_frag_end
        has_sel = sel_start is not None and sel_end is not None
        if has_sel and sel_start > sel_end:
            sel_start, sel_end = sel_end, sel_start

        merged = self._cached_merged
        handlers = self._cached_handlers
        result = []
        for idx in range(len(merged)):
            style, text = merged[idx]
            if has_sel and sel_start <= idx <= sel_end:
                style = (style + " class:selected").strip()
            result.append((style, text, handlers[idx]))
        return result

    def _make_frag_handler(self, frag_idx):
        tui = self

        def handler(mouse_event: MouseEvent):
            et = mouse_event.event_type
            if et in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
                if et == MouseEventType.SCROLL_UP:
                    if tui._output_window:
                        if tui._auto_scroll:
                            tui._auto_scroll = False
                            ri = tui._output_window.render_info
                            tui._scroll_y = ri.vertical_scroll if ri else 0
                        tui._scroll_y = max(0, tui._scroll_y - 3)
                        if tui._app:
                            tui._app.invalidate()
                elif et == MouseEventType.SCROLL_DOWN:
                    if tui._output_window:
                        ri = tui._output_window.render_info
                        wh = ri.window_height if ri else 20
                        max_y = max(0, tui._output_line_count - wh)
                        if not tui._auto_scroll:
                            tui._scroll_y = min(tui._scroll_y + 3, max_y)
                            if tui._scroll_y >= max_y:
                                tui._auto_scroll = True
                            if tui._app:
                                tui._app.invalidate()
                return NotImplemented
            if et == MouseEventType.MOUSE_DOWN and mouse_event.button == MouseButton.LEFT:
                tui._sel_frag_start = frag_idx
                tui._sel_frag_end = None
                tui._sel_dragging = True
                tui._sel_dirty = True
                if tui._app:
                    tui._app.invalidate()
            elif et == MouseEventType.MOUSE_MOVE and tui._sel_dragging:
                now = time.monotonic()
                if now - tui._last_mouse_time < _MOUSE_THROTTLE_SEC:
                    return
                tui._last_mouse_time = now
                if tui._sel_frag_end != frag_idx:
                    tui._sel_frag_end = frag_idx
                    tui._sel_dirty = True
                    if tui._app:
                        tui._app.invalidate()
            elif et == MouseEventType.MOUSE_UP and mouse_event.button == MouseButton.LEFT:
                if tui._sel_dragging:
                    tui._sel_frag_end = frag_idx
                    tui._sel_dragging = False
                    tui._sel_dirty = True
                    if tui._app:
                        tui._app.invalidate()
                    asyncio.ensure_future(tui._copy_selection_async())

        return handler

    async def _copy_selection_async(self):
        s, e = self._sel_frag_start, self._sel_frag_end
        if s is None or e is None:
            return
        if s > e:
            s, e = e, s
        self._sel_frag_start = None
        self._sel_frag_end = None
        self._sel_dirty = True
        if self._app:
            self._app.invalidate()
        if s >= len(self._split_plain) or e >= len(self._split_plain):
            return
        parts = self._split_plain[s : e + 1]
        selected = "".join(parts)
        if not selected.strip():
            return
        n_lines = selected.count("\n") + 1
        copied = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbcopy",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate(selected.encode())
            copied = True
        except Exception:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "xclip",
                    "-selection",
                    "clipboard",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate(selected.encode())
                copied = True
            except Exception:
                pass
        if copied:
            self._copy_msg = f"Copied ({n_lines} lines)"
            self._copy_msg_until = time.monotonic() + 2.0
            if self._app:
                self._app.invalidate()

    def _get_status_ft(self) -> FormattedText:
        if not self.agent_ctx:
            return FormattedText([("class:status-bar", " Initializing...")])
        parts: list[tuple[str, str]] = []
        m = len(self.agent_ctx.messages)
        i = self.agent_ctx.iteration
        t = f"{self.agent_ctx.total_tokens:,}" if self.agent_ctx.total_tokens else "0"
        model = self.agent_ctx.model or "?"
        provider = self._provider_display
        parts.append(("class:status-bar", f" {provider}/{model}"))
        agent = self.agent_ctx.metadata.get("_current_agent", "default")
        if agent != "default":
            parts.append(("class:status-agent", f" → {agent}"))
        parts.append(("class:status-bar", f"  Msgs:{m}"))
        parts.append(("class:status-bar", f"  Tok:{t}"))
        parts.append(("class:status-bar", f"  Iter:{i}"))
        if self._agent_running:
            parts.append(("class:status-running", "  RUNNING"))
        else:
            parts.append(("class:status-bar", "  idle"))
        if self._pending_inputs:
            parts.append(("class:status-queue", f"  Queue:{len(self._pending_inputs)}"))
        if self._copy_msg and time.monotonic() < self._copy_msg_until:
            parts.append(("class:status-running", f"  {self._copy_msg}"))
        else:
            self._copy_msg = ""
        return FormattedText(parts)

    async def _render_worker(self):
        _log = logging.getLogger(__name__)
        loop = asyncio.get_event_loop()
        while True:
            try:
                items: list[tuple] = []
                try:
                    item = await self._render_queue.get()
                    items.append(item)
                except asyncio.CancelledError:
                    break
                deadline = loop.time() + 0.03
                while len(items) < 20:
                    timeout = max(0, deadline - loop.time())
                    if timeout <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._render_queue.get(), timeout=timeout)
                        items.append(item)
                    except TimeoutError:
                        break
                    except asyncio.CancelledError:
                        break
                if not items:
                    continue

                results = await loop.run_in_executor(None, self._render_batch_sync, items)
                for action in results:
                    action()
                for _ in items:
                    self._render_queue.task_done()
                self._cache_dirty = True
                self._sel_dirty = True
                if self._app:
                    self._app.invalidate()
            except asyncio.CancelledError:
                break
            except Exception:
                logging.getLogger(__name__).warning("render worker error", exc_info=True)

    def _render_batch_sync(self, items: list[tuple]) -> list:
        results = []
        console = Console(force_terminal=True, width=self._cached_width, color_system="truecolor")
        for item in items:
            kind = item[0]
            try:
                if kind == "append_ansi":
                    ansi = item[1]
                    results.append(lambda a=ansi: self._ansi_segments.append(a))

                elif kind == "markdown":
                    md_text = item[1]
                    ansi = _md2a_static(console, md_text)
                    if ansi:
                        results.append(lambda a=ansi: self._ansi_segments.append(a))

                elif kind == "rich_text":
                    text_content, style = item[1], item[2]
                    ansi = _r2a_static(console, Text(text_content, style=style))
                    if ansi:
                        results.append(lambda a=ansi: self._ansi_segments.append(a))

                elif kind == "thinking_append_ansi":
                    seg_idx = item[1]
                    ansi = item[2]
                    if ansi and seg_idx is not None and seg_idx < len(self._ansi_segments):
                        results.append(
                            lambda a=ansi, si=seg_idx: self._ansi_segments.__setitem__(si, self._ansi_segments[si] + a)
                        )

                elif kind == "thinking_delta":
                    seg_idx = item[1]
                    chunk = item[2]
                    ansi = _r2a_static(console, Text(chunk, style="dim italic"))
                    if ansi and seg_idx is not None and seg_idx < len(self._ansi_segments):
                        results.append(
                            lambda a=ansi, si=seg_idx: self._ansi_segments.__setitem__(si, self._ansi_segments[si] + a)
                        )

                elif kind == "tool_pair":
                    display, style, result_preview = item[1], item[2], item[3]
                    call_ansi = _r2a_static(console, Text(f"  → {display}", style=style))
                    if call_ansi:
                        results.append(lambda a=call_ansi: self._ansi_segments.append(a))
                    result_text = f"     ← {result_preview}"
                    if "\n" in result_text:
                        result_text = result_text.replace("\n", "\n     ") + "\n"
                    result_ansi = _r2a_static(console, Text(result_text, style="dim"))
                    if result_ansi:
                        results.append(lambda a=result_ansi: self._ansi_segments.append(a))

                elif kind == "history":
                    msgs = item[1]
                    import json as _json

                    for msg in msgs:
                        try:
                            role = msg.get("role", "")
                            content = msg.get("content") or ""
                            reasoning = msg.get("reasoning_content") or ""
                            if role == "user" and content:
                                agent_tag = msg.get("agent", "")
                                if agent_tag and agent_tag != "default":
                                    ansi = _md2a_static(console, f"▶ [{agent_tag}] {content}")
                                else:
                                    ansi = _md2a_static(console, f"▶ {content}")
                                if ansi:
                                    results.append(lambda a=ansi: self._ansi_segments.append(a))
                            elif role == "assistant":
                                if reasoning:
                                    ansi = _r2a_static(
                                        console,
                                        Text(f"Thinking: {reasoning[:200]}", style="dim italic"),
                                    )
                                    if ansi:
                                        results.append(lambda a=ansi: self._ansi_segments.append(a))
                                tool_calls = msg.get("tool_calls") or []
                                for tc in tool_calls:
                                    fn = tc.get("function", {})
                                    args_raw = fn.get("arguments", {})
                                    args = _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                                    display = self._fmt_tool(fn.get("name", ""), args)
                                    ansi = _r2a_static(console, Text(f"  → {display}", style="cyan"))
                                    if ansi:
                                        results.append(lambda a=ansi: self._ansi_segments.append(a))
                                if content:
                                    ansi = _md2a_static(console, content)
                                    if ansi:
                                        results.append(lambda a=ansi: self._ansi_segments.append(a))
                        except Exception:
                            continue
            except Exception:
                continue
        return results

    async def _periodic_stream_flush(self):
        while True:
            try:
                await asyncio.sleep(0.1)
                if self._stream and self._rendered_up_to < len(self._stream):
                    content = self._stream[self._rendered_up_to :]
                    boundary = self._find_paragraph_boundary(content)
                    if boundary > 0:
                        paragraph = content[:boundary]
                        if paragraph.strip():
                            await self._render_queue.put(("markdown", paragraph))
                        toggle_count = paragraph.count("```")
                        if toggle_count % 2 == 1:
                            self._in_code_block = not self._in_code_block
                        self._rendered_up_to += boundary
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _handle_input(self, text: str):
        if text.startswith("/"):
            self._append_dim(f"{text}")
            should_exit = await self._handle_slash(text)
            self._invalidate()
            if should_exit:
                if self._app:
                    self._app.exit()
                return
            return

        self._append_md(f"▶ {text}")
        mentions, clean_text = self._parse_agent_mentions(text)
        if mentions:
            await self._handle_mention_delegation(mentions, clean_text)
            self._invalidate()
            return

        await self._execute_agent(text)
        self._invalidate()

    async def _execute_agent(self, ui: str):
        await self._ensure_conversation()
        if self._conversation_id and not getattr(self.args, "no_persist", False):
            await self._persist_user_message(ui)

        self._stream = ""
        self._thinking_active = False
        self._rendered_up_to = 0
        self._in_code_block = False
        self._sub_agent_tasks = {}
        self._pending_calls.clear()
        self._buffered_tool_pairs.clear()
        self._agent_running = True
        self._abort_flag = False
        self._invalidate()

        try:
            self.agent_ctx.iteration = 0
            self._agent_task = asyncio.create_task(run_agent(self.agent_ctx, ui))
            await self._agent_task
        except asyncio.CancelledError:
            self._append_dim("[interrupted]")
        except Exception as e:
            self._append_rich(Text(f"Error: {e}", style="red"))
        finally:
            self._agent_running = False
            self._agent_task = None
            self._invalidate()

        if self._conversation_id:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as db:
                await update_conversation(db, self._session_id_str, tokens=self.agent_ctx.total_tokens)

        from crabagent.serve.services.persistence import PersistenceListener

        for cb in self.agent_ctx.event_bus._listeners:
            if hasattr(cb, "__self__") and isinstance(cb.__self__, PersistenceListener):
                await cb.__self__.finalize()

        await self._render_queue.join()

        while self._pending_inputs:
            next_ui = self._pending_inputs.pop(0)
            self._append_md(f"▶ {next_ui}")
            mentions, clean_text = self._parse_agent_mentions(next_ui)
            if mentions:
                await self._handle_mention_delegation(mentions, clean_text)
            else:
                await self._execute_agent(clean_text or next_ui)

    async def _on_agent_event(self, event: AgentEvent):
        if event.type == EventType.THINKING_DELTA:
            chunk = event.data.get("text", "")
            if not chunk:
                return
            if not self._thinking_active:
                self._thinking_active = True
                self._append_rich(Text("Thinking: ", style="dim italic"))
                self._thinking_seg_idx = len(self._ansi_segments) - 1
            await self._render_queue.put(("thinking_delta", self._thinking_seg_idx, chunk))

        elif event.type == EventType.THINKING_DONE:
            if self._thinking_active:
                self._thinking_active = False
                self._thinking_seg_idx = None
                for pair in self._buffered_tool_pairs:
                    await self._render_queue.put(("tool_pair", pair[0], pair[1], pair[2]))
                self._buffered_tool_pairs.clear()
            self._invalidate()

        elif event.type == EventType.TEXT_DELTA:
            if self._thinking_active:
                self._thinking_active = False
                self._thinking_seg_idx = None
                for pair in self._buffered_tool_pairs:
                    await self._render_queue.put(("tool_pair", pair[0], pair[1], pair[2]))
                self._buffered_tool_pairs.clear()
            self._stream += event.data.get("text", "")

        elif event.type == EventType.TEXT_DONE:
            remaining = self._stream[self._rendered_up_to :]
            if remaining.strip():
                await self._render_queue.put(("markdown", remaining))
            self._stream = ""
            self._rendered_up_to = 0
            self._in_code_block = False
            self._invalidate()

        elif event.type == EventType.TOOL_CALL:
            tool_name = event.data.get("name", "")
            if tool_name not in (
                "delegate_task",
                "delegate_parallel",
                "handoff_to",
                "list_agents",
            ):
                tool_id = event.data.get("id", "")
                display = self._fmt_tool(tool_name, event.data.get("arguments", {}))
                source = event.data.get("source", "builtin")
                style = "bright_magenta" if source == "mcp" else "cyan"
                if tool_id:
                    self._pending_calls[tool_id] = (display, style)

        elif event.type == EventType.TOOL_RESULT:
            result = event.data.get("result", "")
            result_str = str(result)
            preview = result_str[:200]
            if len(result_str) > 200:
                preview += "..."
            tool_id = event.data.get("id", "")
            call_info = self._pending_calls.pop(tool_id, None)
            if call_info:
                display, style = call_info
                if self._thinking_active:
                    self._buffered_tool_pairs.append((display, style, preview))
                else:
                    await self._render_queue.put(("tool_pair", display, style, preview))
            else:
                await self._render_queue.put(("rich_text", f"  ← {preview}", "dim"))
            self._invalidate()

        elif event.type == EventType.AGENT_ERROR:
            await self._render_queue.put(("rich_text", f"Error: {event.data.get('error')}", "red"))
            self._invalidate()

        elif event.type == EventType.BUDGET_EXHAUSTED:
            await self._render_queue.put(("rich_text", "Budget exhausted, generating summary...", "yellow"))
            self._invalidate()

        elif event.type == EventType.CONTEXT_COMPRESSED:
            orig = event.data.get("original_count", "?")
            comp = event.data.get("compressed_count", "?")
            await self._render_queue.put(("rich_text", f"Context compressed: {orig} → {comp} messages", "dim yellow"))
            self._invalidate()

        elif event.type == EventType.SUB_AGENT_START:
            sub_id = event.data.get("sub_agent_id", "")
            agent_name = event.data.get("agent_name", "?")
            display = event.data.get("display_name", agent_name)
            task_desc = event.data.get("task", "")
            self._sub_agent_tasks[sub_id] = {
                "agent_name": agent_name,
                "display_name": display,
                "task": task_desc,
                "status": "running",
                "tools": 0,
                "current": "starting...",
            }
            await self._render_queue.put(("markdown", f"**▶ {display}** `{task_desc[:80]}`"))
            self._invalidate()

        elif event.type == EventType.SUB_AGENT_TOOL_CALL:
            sub_id = event.data.get("sub_agent_id", "")
            name = event.data.get("name", "")
            args = event.data.get("arguments", {})
            if sub_id in self._sub_agent_tasks:
                t = self._sub_agent_tasks[sub_id]
                t["tools"] += 1
                t["current"] = self._fmt_tool(name, args)

        elif event.type == EventType.SUB_AGENT_END:
            sub_id = event.data.get("sub_agent_id", "")
            display = event.data.get("display_name", "?")
            elapsed = event.data.get("elapsed", 0)
            tokens = event.data.get("tokens", 0)
            iterations = event.data.get("iterations", 0)
            tools = self._sub_agent_tasks.get(sub_id, {}).get("tools", 0)
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "done"
            tok_str = f"{tokens:,}" if tokens else "0"
            await self._render_queue.put(
                (
                    "markdown",
                    f"**✓ {display}** `({elapsed}s, {tok_str} tok, {iterations} steps, {tools} tools)`",
                )
            )
            self._invalidate()

        elif event.type == EventType.SUB_AGENT_ERROR:
            sub_id = event.data.get("sub_agent_id", "")
            agent_name = event.data.get("agent_name", "?")
            error = event.data.get("error", "unknown error")
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "error"
            await self._render_queue.put(("markdown", f"**✗ {agent_name}** Error: {error}"))
            self._invalidate()

        elif event.type == EventType.PIPELINE_START:
            total = event.data.get("total_steps", 0)
            step_agents = event.data.get("step_agents", {})
            step_tasks = event.data.get("step_tasks", {})
            await self._render_queue.put(("markdown", f"**Pipeline** {total} steps"))
            for sid, agent in step_agents.items():
                task = step_tasks.get(sid, "")[:60]
                await self._render_queue.put(("markdown", f"  └ {agent}: {task}"))
            self._invalidate()

        elif event.type == EventType.PIPELINE_STEP_START:
            agent = event.data.get("agent_name", "?")
            task = event.data.get("task", "")[:80]
            await self._render_queue.put(("markdown", f"  **▶ Step** {agent}: `{task}`"))
            self._invalidate()

        elif event.type == EventType.PIPELINE_STEP_END:
            agent = event.data.get("agent_name", "?")
            elapsed = event.data.get("elapsed", 0)
            result_preview = str(event.data.get("result", ""))[:100]
            await self._render_queue.put(("markdown", f"  **✓ Step** {agent} `({elapsed}s)` {result_preview}"))
            self._invalidate()

        elif event.type == EventType.PIPELINE_END:
            total = event.data.get("total", 0)
            ok = event.data.get("success_count", 0)
            fail = event.data.get("fail_count", 0)
            elapsed = event.data.get("total_elapsed", 0)
            icon = "✓" if fail == 0 else "⚠"
            await self._render_queue.put(("markdown", f"**{icon} Pipeline done** `{ok}/{total}` in `{elapsed}s`"))
            self._invalidate()

    def _print_banner(self):
        pass

    async def _handle_new_session(self):
        if getattr(self.args, "no_persist", False):
            self._append_dim("Persistence disabled.")
            return
        if not self._user:
            return
        from crabagent.core.config import settings as _settings

        ws = (self.args.workspace or _settings.workspace).resolve()
        cv = await self._init_conv(self._user.id, str(ws), self.agent_ctx.model if self.agent_ctx else "")
        self._conversation_id = cv.id
        self._session_id_str = cv.session_id
        self._state = {"fm": [True]}
        if self.agent_ctx:
            self.agent_ctx.messages.clear()
            self.agent_ctx.iteration = 0
            self.agent_ctx.total_tokens = 0
            self.agent_ctx.metadata["session_id"] = cv.session_id
            self.agent_ctx.metadata["branch_id"] = "main"
            await self._replace_persistence_listener()
        self._append_dim(f"New session: {cv.session_id[:8]}")

    async def _handle_slash(self, ui: str) -> bool:
        p = ui.split(maxsplit=1)
        cmd = p[0].lower()
        arg = p[1].strip() if len(p) > 1 else ""
        if cmd in ("/exit", "/quit"):
            return True
        if cmd == "/abort":
            return False
        if cmd == "/help":
            self._append_md(
                "/exit /quit  Exit\n/help  Help\n/clear  Clear\n"
                "/history  Stats\n/model [n]  Switch\n/models  List\n"
                "/new  New session\n/sessions  List\n/session [id]  Load\n"
                "/export  export .md\n/provider  Manage\n"
                "/agents  Agent team\n/agent [name]  Switch agent\n/delegate [@agent] [task]  Delegate\n"
                "/agent_stats <name>  Agent stats\n"
                "/runs  Recent run history\n"
                "/memory [list|search|clear]  Team memory\n"
                "/skills  List skills\n/skill <name>  Show skill\n"
                "/abort  Abort running agent\n\n"
                "Scroll: PageUp/PageDown/MouseWheel/Home/End\n"
                "Select text: mouse drag\n"
            )
        elif cmd == "/clear":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            self._reset_output()
            self._append_md(f"**CrabAgent v{__version__}**\n")
        elif cmd == "/history":
            if self.agent_ctx:
                self._append_md(
                    f"M: {len(self.agent_ctx.messages)} "
                    f"T: {self.agent_ctx.total_tokens or 0:,} "
                    f"I: {self.agent_ctx.iteration}"
                )
        elif cmd == "/models":
            ms = await self._fetch_models()
            if ms:
                lines = []
                for i, m in enumerate(ms, 1):
                    is_current = m == (self.agent_ctx.model if self.agent_ctx else None)
                    mark = " *" if is_current else ""
                    lines.append(f"  {i:>2}. {m}{mark}")
                self._append_md("```\n" + "\n".join(lines) + "\n```")
            else:
                self._append_dim("No models.")
        elif cmd == "/model":
            chosen_model = arg.strip()
            if not chosen_model:
                ms = await self._fetch_models()
                if not ms:
                    self._append_dim("No models.")
                    return False
                current = self.agent_ctx.model if self.agent_ctx else None
                items = [(m, f"{m} {'←' if m == current else ''}".strip()) for m in ms]

                async def on_select(m):
                    if self.agent_ctx:
                        self.agent_ctx.model = m
                    from crabagent.core.config import settings as _settings

                    _settings.save_last_model(m)
                    self._append_dim(f"Model: {m}")

                self._selection_popup.show("Select Model", items, on_select)
                return False
            ms = await self._fetch_models()
            try:
                idx = int(chosen_model) - 1
                if 0 <= idx < len(ms):
                    chosen_model = ms[idx]
                else:
                    self._append_dim(f"Invalid #{chosen_model}. Use 1-{len(ms)}")
                    return False
            except ValueError:
                pass
            if self.agent_ctx:
                self.agent_ctx.model = chosen_model
            from crabagent.core.config import settings as _settings

            _settings.save_last_model(chosen_model)
            self._append_dim(f"Model: {chosen_model}")
        elif cmd == "/agent":
            if arg.strip():
                await self._switch_agent(arg.strip())
            else:
                await self._agent_popup()
            return False
        elif cmd == "/export":
            await self._handle_export()
        elif cmd == "/provider":
            await self._handle_provider_dual(arg)
        elif cmd == "/agents":
            await self._handle_agents_dual(arg)
        elif cmd == "/delegate":
            if arg.strip():
                parts = arg.strip().split(maxsplit=1)
                maybe_agent = parts[0].lstrip("@")
                task = parts[1].strip() if len(parts) > 1 else ""
                if not task:
                    self._append_dim("Usage: /delegate @agent task")
                    return False
                self._append_ansi("")
                await self._run_delegation(maybe_agent, task)
            else:
                self._append_dim("Usage: /delegate @agent task")
        elif cmd == "/new":
            await self._handle_new_session()
            self._reset_output()
            self._append_md(f"**CrabAgent v{__version__}**\n")
        elif cmd == "/sessions":
            await self._handle_sessions_popup()
        elif cmd == "/session":
            if not arg.strip():
                self._append_dim("Usage: /session <session_id>")
                return False
            await self._handle_session_load(arg)
        elif cmd == "/memory":
            await self._handle_memory_slash(arg)
        elif cmd == "/skills":
            from crabagent.core.agent.skill.loader import discover_skills
            from crabagent.core.config import settings as _settings

            dirs = _settings.skill_discovery_dirs()
            skills = discover_skills(dirs)
            if not skills:
                self._append_dim("No skills found.")
            else:
                lines = []
                for s in sorted(skills.values(), key=lambda x: x.name):
                    aux = f" ({len(s.auxiliary_files)} files)" if s.auxiliary_files else ""
                    lines.append(f"- **{s.name}**{aux}\n  {s.description}")
                self._append_md("\n".join(lines))
        elif cmd == "/skill":
            if not arg:
                self._append_dim("/skill <name>")
            else:
                from crabagent.core.agent.skill.loader import (
                    discover_skills,
                    format_skill_content,
                )
                from crabagent.core.config import settings as _settings

                dirs = _settings.skill_discovery_dirs()
                skills = discover_skills(dirs)
                skill = skills.get(arg)
                if not skill:
                    names = ", ".join(sorted(skills.keys())) if skills else "(none)"
                    self._append_dim(f"Skill '{arg}' not found. Available: {names}")
                else:
                    self._append_md(f"```\n{format_skill_content(skill)}\n```")
        elif cmd == "/agent_stats":
            if not arg:
                self._append_dim("/agent_stats <name>")
            else:
                await self._handle_agent_stats(arg)
        elif cmd == "/runs":
            await self._handle_runs(arg)
        else:
            self._append_dim(f"Unknown: {cmd}")
        return False

    def _reset_output(self):
        self._ansi_segments.clear()
        self._cached_seg_count = 0
        self._cached_fragments.clear()
        self._cached_merged.clear()
        self._cached_handlers.clear()
        self._cached_line_count = 0
        self._rendered_cache = FormattedText([("", "")])
        self._cache_dirty = True
        self._sel_dirty = True
        self._output_plain_text = ""
        self._split_plain = []

    async def _handle_provider_dual(self, arg: str):
        from crabagent.core.provider_store import (
            PROVIDER_CATALOG,
            create_provider,
            delete_provider,
            get_default_provider,
            list_providers,
            set_default_provider,
        )

        sp = arg.split(maxsplit=1) if arg else []
        sc = sp[0].lower() if sp else "list"
        sa = sp[1].strip() if len(sp) > 1 else ""

        if sc in ("list", ""):
            ps = await list_providers()
            if not ps:
                self._append_dim("No providers. Use `/provider add` to add one.")
                return
            d = await get_default_provider()
            items = []
            for p in ps:
                is_default = d and p.name == d.name
                mark = " ←" if is_default else ""
                display = f"{p.name} ({p.display_name or p.name}){mark}"
                items.append((p.name, display))

            async def on_select(name):
                try:
                    await set_default_provider(name)
                    self._append_dim(f"Default: {name}")
                except Exception as e:
                    self._append_rich(Text(f"Error: {e}", style="red"))

            self._selection_popup.show("Providers (Enter=set default)", items, on_select)

        elif sc == "add":
            parts = (sa or "").split()
            if len(parts) < 3:
                catalog = "\n".join(f"  `{k}`: {v['display_name']}" for k, v in PROVIDER_CATALOG.items())
                self._append_md(
                    f"**Usage:** `/provider add <type> <name> <api_key> [base_url]`\n\n**Types:**\n{catalog}"
                )
                return
            provider_type = parts[0]
            name = parts[1]
            api_key = parts[2]
            base_url = parts[3] if len(parts) > 3 else ""
            if provider_type not in PROVIDER_CATALOG:
                self._append_dim(f"Unknown type: {provider_type}")
                return
            try:
                existing = await list_providers()
                await create_provider(
                    name=name,
                    display_name=PROVIDER_CATALOG[provider_type]["display_name"],
                    provider_type=provider_type,
                    api_key=api_key,
                    base_url=base_url,
                    is_default=len(existing) == 0,
                )
                self._append_md(f"**Provider added:** `{name}`")
            except Exception as e:
                self._append_rich(Text(f"Error: {e}", style="red"))

        elif sc in ("set", "set-default"):
            if not sa:
                self._append_dim("/provider set <name>")
                return
            try:
                await set_default_provider(sa)
                self._append_dim(f"Default: {sa}")
            except Exception as e:
                self._append_rich(Text(f"Error: {e}", style="red"))

        elif sc in ("rm", "remove", "del", "delete"):
            if not sa:
                self._append_dim("/provider rm <name>")
                return
            await delete_provider(sa)
            self._append_dim(f"Removed: {sa}")

        else:
            self._append_dim("/provider {list|add|set|rm}")

    async def _handle_agents_dual(self, arg: str):
        sp = arg.split(maxsplit=1) if arg else []
        sc = sp[0].lower() if sp else "list"

        if sc == "list":
            agents = await self._fetch_all_agents()
            if not agents:
                self._append_dim("No agents. Use `/agents add` in classic TUI mode.")
                return
            enabled_count = sum(1 for a in agents if a.enabled)
            lines = [f"**Agent Team** ({enabled_count}/{len(agents)} active)\n"]
            for a in agents:
                icon = a.icon or "🤖"
                status = "ON" if a.enabled else "OFF"
                default_tag = " [default]" if a.is_default else ""
                model_tag = f" [{a.model}]" if a.model else ""
                lines.append(
                    f"- {icon} **{a.display_name or a.name}**{default_tag} "
                    f"`{status}`{model_tag}\n"
                    f"  Role: {a.role}\n"
                    f"  Goal: {a.goal[:80]}"
                )
            self._append_md("\n".join(lines))
        elif sc in ("add", "edit", "toggle", "rm", "remove", "del", "delete"):
            self._append_md(
                "[dim]Interactive agent management requires classic TUI mode. "
                "Use `crabagent` without `--dual-tui` flag.[/dim]"
            )
        else:
            self._append_dim("/agents {list}")

    async def _agent_popup(self):
        from crabagent.core.agent.agents import load_agent_registry

        agents = await load_agent_registry()
        items = [("default", "🦀 default (All tools)")]
        for a in agents:
            icon = a.get("icon", "") or "🤖"
            tools_n = len(a.get("tools", []))
            label = f"{icon} {a['display_name']} ({a['role'][:20]}) [{tools_n} tools]"
            items.append((a["name"], label))

        async def on_select(name):
            await self._switch_agent(name)

        self._selection_popup.show("Select Agent", items, on_select)

    async def _switch_agent(self, name: str):
        if not self.agent_ctx:
            return

        current = self.agent_ctx.metadata.get("_current_agent", "default")
        if name == current:
            self._append_dim(f"Already using {name}")
            return

        try:
            if name == "default":
                self.agent_ctx.tool_registry = self._full_tool_registry
                self.agent_ctx.current_agent = "default"
                self.agent_ctx.metadata["_current_agent"] = "default"
                if self._full_model:
                    self.agent_ctx.model = self._full_model
                self.agent_ctx.messages.append(
                    {
                        "role": "user",
                        "content": "[Agent Switch] Back to default — all tools restored.",
                        "agent": "default",
                    }
                )
                self._append_dim("Agent: default (all tools)")
            else:
                from crabagent.core.agent.agents import get_agent

                agent = await get_agent(name)
                if not agent:
                    self._append_dim(f"Agent '{name}' not found")
                    return

                from crabagent.core.agent.agent_switch import filter_tool_registry

                filtered = filter_tool_registry(self._full_tool_registry, agent.get("tools"))
                self.agent_ctx.tool_registry = filtered
                if agent.get("model"):
                    self.agent_ctx.model = agent["model"]

                self.agent_ctx.current_agent = name
                self.agent_ctx.metadata["_current_agent"] = name

                from crabagent.core.agent.agents import build_agent_switch_msg

                locale = self.agent_ctx.metadata.get("locale", self.agent_ctx.locale or "en")
                self.agent_ctx.messages.append(build_agent_switch_msg(agent, locale=locale))
                icon = agent.get("icon", "")
                tool_n = len(agent.get("tools", []))
                extra = f" | Model: {agent['model']}" if agent.get("model") else ""
                self._append_dim(f"Agent: {icon} {agent['display_name']} ({tool_n} tools){extra}")

            if self._conversation_id:
                from crabagent.core.database import async_session_factory
                from crabagent.serve.services.conversation import update_conversation

                async with async_session_factory() as db:
                    await update_conversation(db, self._session_id_str, agent=name)
        except Exception as e:
            self._append_dim(f"Switch failed: {e}")

        self._invalidate()

    async def _handle_sessions_popup(self):
        if getattr(self.args, "no_persist", False):
            self._append_dim("Persistence disabled.")
            return
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.conversation import list_conversations

        async with async_session_factory() as db:
            convs = await list_conversations(db, self._user.id)
        if not convs:
            self._append_dim("No sessions.")
            return
        items = []
        for c in convs[:20]:
            title = c.title or "(untitled)"
            ts = c.updated_at.strftime("%m-%d %H:%M") if c.updated_at else ""
            cur = " ←" if c.id == self._conversation_id else ""
            display = f"{c.session_id[:8]} {title} [{ts}]{cur}"
            items.append((c.session_id, display))

        async def on_select(sid):
            try:
                await self._handle_session_load(sid)
            except Exception as e:
                self._append_dim(f"Session load failed: {e}")

        self._selection_popup.show("Sessions", items, on_select)

    async def _handle_session_load(self, arg: str):
        if getattr(self.args, "no_persist", False):
            self._append_dim("Persistence disabled.")
            return
        chosen_sid = arg.strip()
        cv, hist, ms = await self._load_conv(chosen_sid, self._user.id)
        if not cv:
            self._append_dim("Session not found.")
            return
        self._conversation_id = cv.id
        self._session_id_str = cv.session_id
        self._state = {"fm": [False]}
        if self.agent_ctx:
            self.agent_ctx.messages = hist
            self.agent_ctx.iteration = 0
            self.agent_ctx.total_tokens = cv.tokens or 0
            self.agent_ctx.metadata["session_id"] = cv.session_id
            self.agent_ctx.metadata["branch_id"] = "main"
            if cv.model:
                self.agent_ctx.model = cv.model
            if cv.agent:
                self.agent_ctx.current_agent = cv.agent
                self.agent_ctx.metadata["_current_agent"] = cv.agent
            await self._replace_persistence_listener()
        self._reset_output()
        self._append_dim(f"Loaded session {cv.session_id[:8]} ({len(hist)} messages)")
        self._invalidate()

        if hist:
            to_show = hist[-5:] if len(hist) > 5 else hist
            hidden = len(hist) - len(to_show)
            if hidden > 0:
                self._append_dim(f"... {hidden} earlier messages hidden ...")
                self._invalidate()
                await asyncio.sleep(0)

            await self._render_queue.put(("history", to_show))
            self._invalidate()

    async def _handle_runs(self, arg: str):
        if getattr(self.args, "no_persist", False) or not self._user:
            self._append_dim("Persistence disabled.")
            return
        from crabagent.core.database import run_record_list

        parts = arg.split()
        limit = 10
        agent_filter = ""
        for p in parts:
            if p.isdigit():
                limit = min(int(p), 50)
            else:
                agent_filter = p

        runs = await run_record_list(
            user_id=self._user.id,
            agent_name=agent_filter,
            limit=limit,
        )
        if not runs:
            self._append_dim("No runs found.")
            return
        import datetime as _dt

        lines = [f"**Recent Runs** ({len(runs)})\n"]
        for r in runs:
            status_icon = {"completed": "✓", "failed": "✗", "running": "▶"}.get(r.get("status", ""), "?")
            name = r.get("agent_name", "?")
            elapsed = r.get("elapsed", 0)
            elapsed_str = f"{elapsed}s" if elapsed else ""
            tokens = r.get("tokens_used", 0)
            tok_str = f"{tokens:,} tok" if tokens else ""
            summary = (r.get("task_summary") or "")[:50]
            ts = r.get("started_at", 0)
            time_str = _dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""
            meta_parts = [p for p in [elapsed_str, tok_str] if p]
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"  {status_icon} {name} `{summary}`{meta} [{time_str}]")
        self._append_md("\n".join(lines))

    async def _handle_export(self):
        if not self._conversation_id:
            self._append_dim("No conversation.")
            return
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import get_messages

        async with async_session_factory() as db:
            msgs = await get_messages(db, self._conversation_id)
        fn = f"crabagent-export-{self._session_id_str[:8]}.md"
        with open(fn, "w") as f:
            f.write("# CrabAgent\n\n")
            for m in msgs:
                c = (m.content or "").strip()
                if not c:
                    continue
                if m.role == "assistant":
                    f.write(f"{c}\n\n")
                elif m.role == "user":
                    f.write(f"▶ {c}\n\n")
        self._append_dim(f"→ {fn}")


async def run_dual_tui(args):
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.StreamHandler) and handler.stream in (
            sys.stdout,
            sys.stderr,
        ):
            root_logger.removeHandler(handler)
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        import tempfile as _tempfile
        _log_path = os.path.join(_tempfile.gettempdir(), "crabagent.log")
        fh = logging.FileHandler(_log_path, mode="a")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(fh)

    logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)

    from crabagent.core import configure_litellm

    configure_litellm()
    await DualPanelTui(args).run()

