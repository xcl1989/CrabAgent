"""CrabAgent TUI — Incremental paragraph-flush Markdown rendering with spinner."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from crabagent import __version__
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType

PROMPT_STYLE = Style.from_dict({"toolbar": "bg:#161b22 #8b949e"})
SLASH_COMMANDS = [
    "/exit",
    "/quit",
    "/help",
    "/clear",
    "/history",
    "/model",
    "/models",
    "/provider",
    "/agents",
    "/agent",
    "/agent_stats",
    "/delegate",
    "/memory",
    "/new",
    "/sessions",
    "/session",
    "/skills",
    "/skill",
    "/export",
    "/abort",
]


class TuiSession:
    def __init__(self, args):
        self.args = args
        self.agent_ctx: AgentContext | None = None
        self.console = Console()
        self._tool_buffer: dict[str, dict] = {}
        self._live: Live | None = None
        self._sub_live: Live | None = None
        self._stream = ""
        self._thinking_active = False
        self._rendered_up_to = 0
        self._in_code_block = False
        self._sub_agent_tasks: dict[str, dict] = {}
        self._provider_display = "default"
        self._conversation_id = None
        self._session_id_str = None
        self._user = None
        self._state = {}
        self._agent_running = False
        self._pending_inputs: list[str] = []
        self._stdin_queue = None
        self._raw_input_active = False

    async def run(self):
        import queue as thread_queue
        import sys as _sys
        import threading as _threading

        await self._initialize()
        if not self.agent_ctx:
            return
        self._print_banner()
        self.agent_ctx.event_bus.subscribe(self._on_agent_event)
        completer = await self._build_completer()
        session = PromptSession(history=InMemoryHistory(), completer=completer, style=PROMPT_STYLE)
        self._stdin_queue = thread_queue.Queue(maxsize=10)

        # Persistent raw stdin reader — only active when _raw_input_active is True
        def _read_stdin():
            import time as _t

            buf = ""
            while True:
                if not self._raw_input_active:
                    _t.sleep(0.1)
                    buf = ""
                    continue
                try:
                    ch = _sys.stdin.read(1)
                    if not ch:
                        break
                    if not self._raw_input_active:
                        buf = ""
                        continue
                    if ch in ("\n", "\r"):
                        if buf.strip():
                            try:
                                self._stdin_queue.put_nowait(buf)
                            except thread_queue.Full:
                                pass
                        buf = ""
                    elif ch == "\x03":
                        try:
                            self._stdin_queue.put_nowait("/abort")
                        except thread_queue.Full:
                            pass
                        buf = ""
                    elif ch and 32 <= ord(ch) <= 126:
                        buf += ch
                except Exception:
                    break

        _stdin_thread = _threading.Thread(target=_read_stdin, daemon=True)
        _stdin_thread.start()

        while True:
            if self._pending_inputs:
                ui = self._pending_inputs.pop(0)
                if self._pending_inputs:
                    self.console.print(f"[dim]Processing queued ({len(self._pending_inputs)} remaining)...[/dim]")
            else:
                status = self._make_status_bar()
                try:
                    ui = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: session.prompt([("class:toolbar", status), ("", "\n> ")], multiline=False)
                    )
                except (EOFError, KeyboardInterrupt):
                    await self._cleanup()
                    self.console.print("\n[dim]Bye![/dim]")
                    break
                ui = ui.strip()

            if not ui:
                continue
            if ui.startswith("/"):
                if ui.startswith("/agents") or ui.startswith("/delegate"):
                    completer = await self._build_completer()
                    session.completer = completer
                if await self._handle_slash(ui):
                    await self._cleanup()
                    break
                continue

            mentions, clean_text = self._parse_agent_mentions(ui)
            if mentions:
                await self._handle_mention_delegation(mentions, clean_text)
                continue

            await self._execute_agent(clean_text or ui)

            # Process any queued input accumulated during execution
            while self._pending_inputs:
                next_ui = self._pending_inputs.pop(0)
                self.console.print(f"\n[dim]Processing queued ({len(self._pending_inputs)} remaining)...[/dim]")
                mentions, clean_text = self._parse_agent_mentions(next_ui)
                if mentions:
                    await self._handle_mention_delegation(mentions, clean_text)
                else:
                    await self._execute_agent(clean_text or next_ui)

            self.console.print()

    def _make_status_bar(self) -> str:
        if not self.agent_ctx:
            return ""
        m = len(self.agent_ctx.messages)
        i = self.agent_ctx.iteration
        t = f"{self.agent_ctx.total_tokens:,}" if self.agent_ctx.total_tokens else "0"
        tp = len(self._tool_buffer)
        parts = [f"Messages: {m}", f"Tokens: {t}", f"Iterations: {i}"]
        if tp:
            parts.append(f"Tools: {tp}")
        return f" [{self._provider_display}/{self.agent_ctx.model or '?'}] {' | '.join(parts)} "

    def _start_spinner(self):
        if not self._live:
            self._live = Live(
                Spinner("dots", Text(" Generating...", style="dim")),
                console=self.console,
                refresh_per_second=4,
                screen=False,
                transient=True,
            )
            self._live.start()

    def _stop_live(self):
        if self._live:
            self._live.stop()
            self._live = None
        if self._sub_live:
            self._sub_live.stop()
            self._sub_live = None

    def _find_paragraph_boundary(self, text):
        in_code = self._in_code_block
        last_boundary = 0
        i = 0
        while i < len(text):
            if text[i : i + 3] == "```":
                in_code = not in_code
                i += 3
                continue
            if not in_code and i + 1 < len(text) and text[i] == "\n" and text[i + 1] == "\n":
                last_boundary = i + 2
            i += 1
        return last_boundary

    def _flush_completed_paragraphs(self):
        content = self._stream[self._rendered_up_to :]
        if not content.strip():
            return
        boundary = self._find_paragraph_boundary(content)
        if boundary <= 0:
            return
        to_print = content[:boundary]
        self._stop_live()
        if to_print.strip():
            self.console.print(Markdown(to_print))
        toggle_count = to_print.count("```")
        if toggle_count % 2 == 1:
            self._in_code_block = not self._in_code_block
        self._rendered_up_to += boundary
        if self._stream[self._rendered_up_to :]:
            self._start_spinner()

    def _stop_tool_live(self):
        self._tool_buffer.clear()

    def _drain_stdin_queue(self):
        import queue as thread_queue

        try:
            while True:
                self._stdin_queue.get_nowait()
        except thread_queue.Empty:
            pass

    async def _execute_agent(self, ui: str):
        """Run agent with raw input collection for queuing."""
        import queue as thread_queue

        await self._ensure_conversation()
        if self._conversation_id and not getattr(self.args, "no_persist", False):
            await self._persist_user_message(ui)
        self.console.print()
        self._stream = ""
        self._thinking_active = False
        self._rendered_up_to = 0
        self._in_code_block = False
        self._sub_agent_tasks = {}

        self._agent_running = True
        self._raw_input_active = True
        await asyncio.sleep(0.05)  # let prompt_toolkit finish releasing stdin
        # Drain any stale characters from the queue
        self._drain_stdin_queue()

        try:
            self.agent_ctx.iteration = 0
            agent_task = asyncio.create_task(run_agent(self.agent_ctx, ui))

            while not agent_task.done():
                try:
                    item = self._stdin_queue.get_nowait()
                    if item in ("/abort", "/exit", "/quit"):
                        agent_task.cancel()
                        self.console.print("\n[dim][aborted by user][/dim]")
                        break
                    if len(self._pending_inputs) >= 5:
                        self.console.print("[dim]Queue full — wait for agent to finish[/dim]")
                    else:
                        self._pending_inputs.append(item)
                        self.console.print(f"[dim]Queued ({len(self._pending_inputs)}/5): {item[:60]}...[/dim]")
                except thread_queue.Empty:
                    await asyncio.sleep(0.3)

            if agent_task.done() and not agent_task.cancelled():
                await agent_task

        except KeyboardInterrupt:
            self.console.print("\n[dim][interrupted][/dim]")
        except Exception as e:
            self.console.print(f"\n[red]Error: {e}[/red]")
        finally:
            self._agent_running = False
            self._raw_input_active = False
            self._drain_stdin_queue()
            self._stop_live()
            self._stop_tool_live()

        if self._conversation_id:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as db:
                await update_conversation(db, self._session_id_str, tokens=self.agent_ctx.total_tokens)

        from crabagent.serve.services.persistence import PersistenceListener

        for cb in self.agent_ctx.event_bus._listeners:
            if hasattr(cb, "__self__") and isinstance(cb.__self__, PersistenceListener):
                await cb.__self__.finalize()

    def _render_sub_live(self):
        running = {k: v for k, v in self._sub_agent_tasks.items() if v.get("status") == "running"}
        if not running:
            if self._sub_live:
                self._sub_live.stop()
                self._sub_live = None
            return
        from rich.text import Text

        text = Text()
        for sub_id, t in running.items():
            display = t["display_name"]
            tools = t["tools"]
            current = t.get("current", "...")
            text.append(f"▶ {display}", style="bold cyan")
            text.append(f"  [{tools} tools]  ", style="dim")
            text.append(f"→ {current[:60]}", style="cyan")
            text.append("\n")
        if self._sub_live:
            self._sub_live.update(text, refresh=True)
        else:
            self._sub_live = Live(text, console=self.console, refresh_per_second=8, screen=False, transient=True)
            self._sub_live.start()

    def _on_agent_event(self, event: AgentEvent):
        if event.type == EventType.THINKING_DELTA:
            if not self._thinking_active:
                self._thinking_active = True
                self.console.print(Text("Thinking: ", style="dim italic"), end="")
            self.console.print(Text(event.data.get("text", ""), style="dim"), end="")
        elif event.type == EventType.THINKING_DONE:
            self._thinking_active = False
            self.console.print()
        elif event.type == EventType.TEXT_DELTA:
            if self._thinking_active:
                self._thinking_active = False
                self.console.print()
            self._stop_tool_live()
            self._stream += event.data.get("text", "")
            self._start_spinner()
            self._flush_completed_paragraphs()
        elif event.type == EventType.TEXT_DONE:
            remaining = self._stream[self._rendered_up_to :]
            self._stop_live()
            if remaining.strip():
                self.console.print(Markdown(remaining))
            elif not self._stream.strip():
                self.console.print()
            self._stream = ""
            self._rendered_up_to = 0
            self._in_code_block = False
        elif event.type == EventType.TOOL_CALL:
            tool_name = event.data.get("name", "")
            if tool_name in ("delegate_task", "delegate_parallel", "handoff_to", "list_agents"):
                pass
            else:
                source = event.data.get("source", "builtin")
                display = self._fmt_tool(tool_name, event.data.get("arguments", {}))
                style = "bright_magenta" if source == "mcp" else "cyan"
                self._stop_live()
                self.console.print(Text(f"  → {display}", style=style))
        elif event.type == EventType.TOOL_RESULT:
            pass
        elif event.type == EventType.AGENT_ERROR:
            self._stop_live()
            self._stop_tool_live()
            self.console.print(f"[red]Error: {event.data.get('error')}[/red]")
        elif event.type == EventType.BUDGET_EXHAUSTED:
            self.console.print("\n[yellow]Budget exhausted, generating summary...[/yellow]")
        elif event.type == EventType.CONTEXT_COMPRESSED:
            orig = event.data.get("original_count", "?")
            comp = event.data.get("compressed_count", "?")
            self.console.print(f"\n  [dim yellow]Context compressed: {orig} \u2192 {comp} messages[/dim yellow]")
        elif event.type == EventType.SUB_AGENT_START:
            self._stop_live()
            sub_id = event.data.get("sub_agent_id", "")
            agent_name = event.data.get("agent_name", "?")
            display = event.data.get("display_name", agent_name)
            task = event.data.get("task", "")
            self._sub_agent_tasks[sub_id] = {
                "agent_name": agent_name,
                "display_name": display,
                "task": task,
                "status": "running",
                "tools": 0,
                "current": "starting...",
            }
            self._render_sub_live()
        elif event.type == EventType.SUB_AGENT_TEXT_DELTA:
            sub_id = event.data.get("sub_agent_id", "")
            if sub_id in self._sub_agent_tasks:
                t = self._sub_agent_tasks[sub_id]
                if t.get("current") == "starting...":
                    t["current"] = "thinking..."
                    self._render_sub_live()
        elif event.type == EventType.SUB_AGENT_TOOL_CALL:
            sub_id = event.data.get("sub_agent_id", "")
            name = event.data.get("name", "")
            args = event.data.get("arguments", {})
            if sub_id in self._sub_agent_tasks:
                t = self._sub_agent_tasks[sub_id]
                t["tools"] += 1
                t["current"] = self._fmt_tool(name, args)
                self._render_sub_live()
        elif event.type == EventType.SUB_AGENT_TOOL_RESULT:
            pass
        elif event.type == EventType.SUB_AGENT_END:
            sub_id = event.data.get("sub_agent_id", "")
            display = event.data.get("display_name", "?")
            elapsed = event.data.get("elapsed", 0)
            tokens = event.data.get("tokens", 0)
            iterations = event.data.get("iterations", 0)
            tools = self._sub_agent_tasks.get(sub_id, {}).get("tools", 0)
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "done"
            if self._sub_live:
                self._sub_live.stop()
                self._sub_live = None
            tok_str = f"{tokens:,}" if tokens else "0"
            self.console.print(
                f"  [bold green]\u2713 {display}[/bold green] "
                f"[dim]({elapsed}s, {tok_str} tok, {iterations} steps, {tools} tools)[/dim]"
            )
            still_running = any(t.get("status") == "running" for t in self._sub_agent_tasks.values())
            if still_running:
                self._render_sub_live()
        elif event.type == EventType.SUB_AGENT_ERROR:
            if self._sub_live:
                self._sub_live.stop()
                self._sub_live = None
            sub_id = event.data.get("sub_agent_id", "")
            agent_name = event.data.get("agent_name", "?")
            error = event.data.get("error", "unknown error")
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "error"
            self.console.print(f"  [bold red]\u2717 {agent_name}[/bold red] [red]Error: {error}[/red]")
            still_running = any(t.get("status") == "running" for t in self._sub_agent_tasks.values())
            if still_running:
                self._render_sub_live()

    def _fmt_tool(self, name: str, args: dict) -> str:
        if name == "read" and "file_path" in args:
            return f"read {args['file_path']}"
        if name in ("write", "edit") and "file_path" in args:
            return f"{name} {args['file_path']}"
        if name == "bash" and "command" in args:
            return f"bash {str(args['command'])[:80]}"
        if name in ("web_search", "web_scrape"):
            q = args.get("query") or args.get("url") or ""
            return f"{name} {str(q)[:60]}"
        k = list(args.keys())
        return f"{name} {k[0]}={str(args[k[0]])[:60]}" if k else name

    def _print_banner(self):
        self.console.print(
            f"[bold]CrabAgent v{__version__}[/bold]\n"
            f"  provider: {self._provider_display}  "
            f"model: {self.agent_ctx.model or 'default'}\n"
            f"  workspace: {self.agent_ctx.workspace}\n"
        )

    async def _handle_slash(self, ui: str) -> bool:
        p = ui.split(maxsplit=1)
        cmd = p[0].lower()
        arg = p[1].strip() if len(p) > 1 else ""
        if cmd in ("/exit", "/quit"):
            return True
        if cmd == "/abort":
            if self._agent_running:
                self.console.print("[dim]Aborting current agent...[/dim]")
                try:
                    self._stdin_queue.put_nowait("/abort")
                except Exception:
                    pass
            else:
                self.console.print("[dim]No agent running.[/dim]")
            return False
        if cmd == "/help":
            self.console.print(
                "/exit /quit  Exit\n/help  Help\n/clear  Clear\n"
                "/history  Stats\n/model [n]  Switch\n/models  List\n"
                "/new  New session\n/sessions  List\n/session [id]  Load\n"
                "/export  \u2192 .md\n/provider  Manage\n"
                "/agents  Agent team\n/delegate [@agent] [task]  Delegate\n"
                "/agent_stats <name>  Agent stats\n"
                "/memory [list|search|clear]  Team memory\n"
                "/skills  List skills\n/skill <name>  Show skill\n"
                "/abort  Abort running agent\n"
            )
        elif cmd == "/clear":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            self.console.clear()
            self._print_banner()
        elif cmd == "/history":
            if self.agent_ctx:
                self.console.print(
                    f"[dim]M: {len(self.agent_ctx.messages)} "
                    f"T: {self.agent_ctx.total_tokens or 0:,} "
                    f"I: {self.agent_ctx.iteration}[/dim]"
                )
        elif cmd == "/models":
            ms = await self._fetch_models()
            if ms:
                for i, m in enumerate(ms, 1):
                    is_current = m == (self.agent_ctx.model if self.agent_ctx else None)
                    mark = " [bold]*[/bold]" if is_current else ""
                    self.console.print(f"  {i:>2}. {m}{mark}")
            else:
                self.console.print("[dim]No models.[/dim]")
        elif cmd == "/model":
            chosen_model = arg.strip() if arg else None
            if not chosen_model:
                ms = await self._fetch_models()
                if not ms:
                    self.console.print("[dim]No models.[/dim]")
                    return
                for i, m in enumerate(ms, 1):
                    mark = " [bold]*[/bold]" if m == (self.agent_ctx.model if self.agent_ctx else None) else ""
                    self.console.print(f"  {i:>2}. {m}{mark}")
                try:
                    choice = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("Choice (# or model_name, Enter=cancel): ").strip()
                    )
                except (EOFError, KeyboardInterrupt):
                    return
                if not choice:
                    return
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(ms):
                        chosen_model = ms[idx]
                    else:
                        self.console.print("[dim]Invalid.[/dim]")
                        return
                except ValueError:
                    chosen_model = choice
            if self.agent_ctx:
                self.agent_ctx.model = chosen_model
            settings.save_last_model(chosen_model)
            self.console.print(f"[dim]Model: {chosen_model}[/dim]")
        elif cmd == "/export":
            await self._handle_export()
        elif cmd == "/provider":
            await self._handle_provider_slash(arg)
        elif cmd == "/agents":
            await self._handle_agents_slash(arg)
        elif cmd == "/delegate":
            await self._handle_delegate_slash(arg)
        elif cmd == "/new":
            await self._handle_new_session()
        elif cmd == "/sessions":
            await self._handle_sessions_list()
        elif cmd == "/session":
            await self._handle_session_load(arg)
        elif cmd == "/memory":
            await self._handle_memory_slash(arg)
        elif cmd == "/skills":
            from crabagent.core.agent.skill.loader import discover_skills
            from crabagent.core.config import settings as _settings

            dirs = _settings.skill_discovery_dirs()
            skills = discover_skills(dirs)
            if not skills:
                self.console.print("[dim]No skills found.[/dim]")
            else:
                for s in sorted(skills.values(), key=lambda x: x.name):
                    aux = f" ({len(s.auxiliary_files)} files)" if s.auxiliary_files else ""
                    self.console.print(f"  [bold]{s.name}[/bold]{aux}")
                    self.console.print(f"    {s.description}")
        elif cmd == "/skill":
            if not arg:
                self.console.print("[dim]/skill <name>[/dim]")
            else:
                from crabagent.core.agent.skill.loader import discover_skills, format_skill_content
                from crabagent.core.config import settings as _settings

                dirs = _settings.skill_discovery_dirs()
                skills = discover_skills(dirs)
                skill = skills.get(arg)
                if not skill:
                    names = ", ".join(sorted(skills.keys())) if skills else "(none)"
                    self.console.print(f"[dim]Skill '{arg}' not found. Available: {names}[/dim]")
                else:
                    self.console.print(format_skill_content(skill))
        elif cmd == "/agent_stats":
            if not arg:
                self.console.print("[dim]/agent_stats <name>[/dim]")
            else:
                await self._handle_agent_stats(arg)
        else:
            self.console.print(f"[dim]Unknown: {cmd}[/dim]")
        return False

    async def _handle_memory_slash(self, arg: str):
        uid = self._user.id if self._user else 0
        if not uid:
            self.console.print("[dim]No user.[/dim]")
            return
        sp = arg.split(maxsplit=1) if arg else []
        sc = sp[0].lower() if sp else "list"
        sa = sp[1].strip() if len(sp) > 1 else ""

        if sc == "list":
            from crabagent.core.database import agent_memory_list_all

            items = await agent_memory_list_all(uid)
            if not items:
                self.console.print("[dim]No memories.[/dim]")
                return
            self.console.print(f"[bold]Memories ({len(items)})[/bold]\n")
            for item in items:
                mt = item["memory_type"]
                agent_tag = f" [{item['agent_name']}]" if item["agent_name"] else ""
                preview = item["content"]
                if len(preview) > 100:
                    preview = preview[:100] + "..."
                self.console.print(f"  {item['key']} ({mt}{agent_tag}, imp={item['importance']:.1f}): {preview}")
        elif sc in ("search", "find"):
            if not sa:
                self.console.print("[dim]/memory search <query>[/dim]")
                return
            from crabagent.core.database import agent_memory_search

            results = await agent_memory_search(uid, sa)
            if not results:
                self.console.print(f"[dim]No results for '{sa}'.[/dim]")
            else:
                for r in results:
                    self.console.print(f"  {r['key']}: {r['content'][:120]}")
        elif sc == "clear":
            from crabagent.core.database import agent_memory_clear

            n = await agent_memory_clear(uid)
            self.console.print(f"[dim]Cleared {n} memories.[/dim]")
        else:
            self.console.print("[dim]/memory {list|search|clear}[/dim]")

    async def _handle_agent_stats(self, name: str):
        uid = self._user.id if self._user else 0
        if not uid:
            self.console.print("[dim]No user.[/dim]")
            return
        from crabagent.core.database import agent_memory_list_all, task_record_stats

        stats = await task_record_stats(uid, name)
        if stats["total"] == 0:
            self.console.print(f"[dim]No task records for agent '{name}'.[/dim]")
            return
        lessons = await agent_memory_list_all(uid, memory_type="agent_lesson")
        agent_lessons = [item for item in lessons if item["agent_name"] == name]
        rule_count = sum(1 for item in agent_lessons if item.get("source") == "rule")
        llm_count = sum(1 for item in agent_lessons if item.get("source") == "llm")
        cats: dict[str, int] = {}
        for item in agent_lessons:
            tc = item.get("task_category", "general") or "general"
            cats[tc] = cats.get(tc, 0) + 1
        cat_parts = [f"{c}({n})" for c, n in sorted(cats.items(), key=lambda x: -x[1])[:4]]

        self.console.print(f"[bold]📊 Agent: {name}[/bold]")
        self.console.print(
            f"  总任务: {stats['total']}    成功率: {stats['success_rate']}%    "
            f"平均耗时: {stats['avg_elapsed']}s    平均 tokens: {stats['avg_tokens']}"
        )
        self.console.print(f"  总 lessons: {len(agent_lessons)} (规则: {rule_count}, LLM: {llm_count})")
        if cat_parts:
            self.console.print(f"  常用类别: {', '.join(cat_parts)}")
        if agent_lessons:
            self.console.print("  最近 lessons:")
            for item in agent_lessons[:5]:
                src = item.get("source", "")
                tag = f"[{src}]" if src else ""
                self.console.print(f"    - {tag} {item['content'][:100]}")

    async def _handle_export(self):
        if not self._conversation_id:
            self.console.print("[dim]No conversation.[/dim]")
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
        self.console.print(f"[dim]→ {fn}[/dim]")

    async def _handle_provider_slash(self, arg: str):
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
        if sc == "list":
            ps = await list_providers()
            if not ps:
                self.console.print("[dim]No providers.[/dim]")
                return
            d = await get_default_provider()
            for p in ps:
                is_default = d and p.name == d.name
                mark = " [bold][default][/bold]" if is_default else ""
                self.console.print(f"  {p.name} ({p.display_name or p.name}){mark}")
        elif sc == "add":
            print("\nAvailable:")
            for k, v in PROVIDER_CATALOG.items():
                print(f"  {k}: {v['display_name']}")
            pt = input("Provider type: ").strip()
            nm = input("Name: ").strip()
            dp = input("Display (opt): ").strip()
            ak = input("API key: ").strip()
            bu = input("Base URL (opt): ").strip()
            if not pt or not nm or not ak:
                print("Required.")
                return
            try:
                ex = await list_providers()
                await create_provider(
                    name=nm,
                    display_name=dp or nm,
                    provider_type=pt,
                    api_key=ak,
                    base_url=bu or "",
                    is_default=len(ex) == 0,
                )
                print(f"Provider '{nm}' added.")
            except Exception as e:
                print(f"Error: {e}")
        elif sc == "remove":
            if not sa:
                self.console.print("[dim]/provider remove <name>[/dim]")
                return
            await delete_provider(sa)
            self.console.print(f"[dim]Removed: {sa}[/dim]")
        elif sc == "set-default":
            if not sa:
                self.console.print("[dim]/provider set-default <name>[/dim]")
                return
            await set_default_provider(sa)
            self.console.print(f"[dim]Default: {sa}[/dim]")
        else:
            self.console.print("[dim]/provider {list|add|remove|set-default}[/dim]")

    async def _fetch_all_agents(self):
        from sqlalchemy import select

        from crabagent.core.database import AgentProfile, async_session_factory

        async with async_session_factory() as db:
            result = await db.execute(select(AgentProfile).order_by(AgentProfile.name))
            return result.scalars().all()

    async def _handle_agents_slash(self, arg: str):
        sp = arg.split(maxsplit=1) if arg else []
        sc = sp[0].lower() if sp else "list"
        sa = sp[1].strip() if len(sp) > 1 else ""

        if sc == "list":
            agents = await self._fetch_all_agents()
            if not agents:
                self.console.print("[dim]No agents. Use /agents add[/dim]")
                return
            enabled_count = sum(1 for a in agents if a.enabled)
            self.console.print(f"[bold]Agent Team[/bold] ({enabled_count}/{len(agents)} active)\n")
            for a in agents:
                icon = a.icon or "🤖"
                status = "[green]ON[/green]" if a.enabled else "[dim]OFF[/dim]"
                default_tag = " [dim][default][/dim]" if a.is_default else ""
                model_tag = f" [dim][{a.model}][/dim]" if a.model else ""
                self.console.print(f"  {icon} [bold]{a.display_name or a.name}[/bold]{default_tag} {status}{model_tag}")
                self.console.print(f"    [dim]Role: {a.role}[/dim]")
                self.console.print(f"    [dim]Goal: {a.goal[:80]}[/dim]")
                tools_val = getattr(a, "tools", None) or ""
                if isinstance(tools_val, list):
                    tools_str = ", ".join(tools_val) if tools_val else "(all)"
                elif isinstance(tools_val, str) and tools_val:
                    import json as _json

                    try:
                        tl = _json.loads(tools_val)
                        tools_str = ", ".join(tl) if tl else "(all)"
                    except Exception:
                        tools_str = "(all)"
                else:
                    tools_str = "(all)"
                self.console.print(f"    [dim]Tools: {tools_str}[/dim]")

        elif sc == "add":
            name = input("Name (lowercase, no spaces): ").strip().lower().replace(" ", "_")
            if not name:
                self.console.print("[dim]Name required.[/dim]")
                return
            display_name = input("Display name: ").strip() or name
            role = input("Role: ").strip()
            if not role:
                self.console.print("[dim]Role required.[/dim]")
                return
            goal = input("Goal: ").strip()
            if not goal:
                self.console.print("[dim]Goal required.[/dim]")
                return
            backstory = input("Backstory (opt): ").strip()
            model = input("Model override (opt): ").strip()
            icon = input("Icon emoji (opt): ").strip() or "🤖"
            print("\nAvailable tools: bash, read, write, edit, glob, grep,")
            print("  web_search, web_scrape, browser, sandbox,")
            print("  shared_get, shared_put, shared_list")
            tools_input = input("Tools (comma-separated, empty=all): ").strip()
            import json as _json

            tools_json = ""
            if tools_input:
                tools_list = [t.strip() for t in tools_input.split(",") if t.strip()]
                if tools_list:
                    tools_json = _json.dumps(tools_list)

            from sqlalchemy import select

            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            try:
                async with async_session_factory() as db:
                    existing = await db.execute(select(AgentProfile).where(AgentProfile.name == name))
                    if existing.scalar_one_or_none():
                        self.console.print(f"[dim]Agent '{name}' already exists.[/dim]")
                        return
                    profile = AgentProfile(
                        user_id=self._user.id if self._user else 1,
                        name=name,
                        display_name=display_name,
                        role=role,
                        goal=goal,
                        backstory=backstory,
                        model=model,
                        icon=icon,
                        is_default=False,
                        tools=tools_json,
                    )
                    db.add(profile)
                    await db.commit()
                invalidate_cache()
                self.console.print(f"[dim]Agent '{name}' created.[/dim]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")

        elif sc == "edit":
            if not sa:
                self.console.print("[dim]/agents edit <name>[/dim]")
                return
            import json as _json

            from sqlalchemy import select

            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            async with async_session_factory() as db:
                result = await db.execute(select(AgentProfile).where(AgentProfile.name == sa))
                profile = result.scalar_one_or_none()
            if not profile:
                self.console.print(f"[dim]Agent '{sa}' not found.[/dim]")
                return
            self.console.print(f"[bold]Editing: {profile.display_name or profile.name}[/bold]")
            self.console.print("[dim]Press Enter to keep current value.[/dim]\n")
            display_name = input(f"Display name [{profile.display_name or profile.name}]: ").strip()
            role = input(f"Role [{profile.role}]: ").strip()
            goal = input(f"Goal [{profile.goal[:60]}]: ").strip()
            backstory = input(f"Backstory [{(profile.backstory or '')[:60]}]: ").strip()
            model = input(f"Model [{profile.model or 'inherit'}]: ").strip()
            icon = input(f"Icon [{profile.icon or '🤖'}]: ").strip()
            current_tools = []
            if profile.tools:
                try:
                    current_tools = _json.loads(profile.tools)
                except Exception:
                    pass
            current_tools_str = ", ".join(current_tools) if current_tools else "all"
            print("\nAvailable tools: bash, read, write, edit, glob, grep,")
            print("  web_search, web_scrape, browser, sandbox,")
            print("  shared_get, shared_put, shared_list")
            tools_input = input(f"Tools [{current_tools_str}]: ").strip()

            async with async_session_factory() as db:
                result = await db.execute(select(AgentProfile).where(AgentProfile.name == sa))
                profile = result.scalar_one_or_none()
                if not profile:
                    return
                if display_name:
                    profile.display_name = display_name
                if role:
                    profile.role = role
                if goal:
                    profile.goal = goal
                if backstory:
                    profile.backstory = backstory
                if model:
                    profile.model = model
                if icon:
                    profile.icon = icon
                if tools_input:
                    tools_list = [t.strip() for t in tools_input.split(",") if t.strip()]
                    profile.tools = _json.dumps(tools_list) if tools_list else ""
                await db.commit()
            invalidate_cache()
            self.console.print(f"[dim]Agent '{sa}' updated.[/dim]")

        elif sc == "toggle":
            if not sa:
                self.console.print("[dim]/agents toggle <name>[/dim]")
                return
            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            async with async_session_factory() as db:
                result = await db.execute(select(AgentProfile).where(AgentProfile.name == sa))
                profile = result.scalar_one_or_none()
                if not profile:
                    self.console.print(f"[dim]Agent '{sa}' not found.[/dim]")
                    return
                profile.enabled = not profile.enabled
                await db.commit()
            invalidate_cache()
            state = "enabled" if profile.enabled else "disabled"
            self.console.print(f"[dim]Agent '{sa}' {state}.[/dim]")

        elif sc in ("rm", "remove", "del", "delete"):
            if not sa:
                self.console.print("[dim]/agents rm <name>[/dim]")
                return
            from sqlalchemy import delete as sql_delete

            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            async with async_session_factory() as db:
                result = await db.execute(select(AgentProfile).where(AgentProfile.name == sa))
                profile = result.scalar_one_or_none()
                if not profile:
                    self.console.print(f"[dim]Agent '{sa}' not found.[/dim]")
                    return
                if profile.is_default:
                    self.console.print("[dim]Default agents cannot be deleted. Use /agents toggle to disable.[/dim]")
                    return
                await db.execute(sql_delete(AgentProfile).where(AgentProfile.name == sa))
                await db.commit()
            invalidate_cache()
            self.console.print(f"[dim]Agent '{sa}' deleted.[/dim]")

        else:
            self.console.print("[dim]/agents {list|add|edit|toggle|rm}[/dim]")

    async def _handle_delegate_slash(self, arg: str):
        from crabagent.core.agent.agents import load_agent_registry

        agents = await load_agent_registry()
        if not agents:
            self.console.print("[dim]No enabled agents. Use /agents add[/dim]")
            return

        if arg.strip():
            parts = arg.split(maxsplit=1)
            maybe_agent = parts[0].lstrip("@")
            task = parts[1].strip() if len(parts) > 1 else ""
            agent_names = [a["name"] for a in agents]
            if maybe_agent in agent_names:
                if not task:
                    task = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input(f"Task for @{maybe_agent}: ").strip()
                    )
                    if not task:
                        self.console.print("[dim]No task.[/dim]")
                        return
                await self._run_delegation(maybe_agent, task)
                return
            task = arg
            self.console.print("[bold]Select agent:[/bold]")
            for i, a in enumerate(agents, 1):
                self.console.print(f"  {i}. {a['icon']} {a['display_name']} ({a['name']})")
            try:
                choice = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("Agent # (or name): ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                return
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(agents):
                    await self._run_delegation(agents[idx]["name"], task)
                else:
                    self.console.print("[dim]Invalid.[/dim]")
            elif choice in agent_names:
                await self._run_delegation(choice, task)
            else:
                self.console.print("[dim]Invalid.[/dim]")
            return

        self.console.print("[bold]Select agent(s):[/bold]")
        for i, a in enumerate(agents, 1):
            self.console.print(f"  {i}. {a['icon']} {a['display_name']} ({a['name']})")
        try:
            choices = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("Agent #s (comma-sep): ").strip()
            )
        except (EOFError, KeyboardInterrupt):
            return
        if not choices:
            return
        selected = []
        agent_names = [a["name"] for a in agents]
        for c in choices.split(","):
            c = c.strip()
            if c.isdigit():
                idx = int(c) - 1
                if 0 <= idx < len(agents):
                    selected.append(agents[idx]["name"])
            elif c in agent_names:
                selected.append(c)
        if not selected:
            self.console.print("[dim]No agents selected.[/dim]")
            return
        try:
            task = await asyncio.get_event_loop().run_in_executor(None, lambda: input("Task: ").strip())
        except (EOFError, KeyboardInterrupt):
            return
        if not task:
            self.console.print("[dim]No task.[/dim]")
            return
        if len(selected) == 1:
            await self._run_delegation(selected[0], task)
        else:
            await self._run_parallel_delegation(selected, task)

    async def _run_delegation(self, agent_name: str, task: str):
        prefix = f'[delegate_task] agent_name="{agent_name}" task="{task}"'
        self.console.print(f"\n[bold]\u25b6 \u2192 @{agent_name} {task}[/bold]")
        self._stream = ""
        self._thinking_active = False
        self._rendered_up_to = 0
        self._in_code_block = False
        self._sub_agent_tasks = {}
        try:
            self.agent_ctx.iteration = 0
            await run_agent(self.agent_ctx, prefix)
        except KeyboardInterrupt:
            self._stop_live()
            self._stop_tool_live()
            self.console.print("\n[dim][interrupted][/dim]")
        except Exception as e:
            self._stop_live()
            self._stop_tool_live()
            self.console.print(f"\n[red]Error: {e}[/red]")
        self._stop_live()
        self._stop_tool_live()

    async def _run_parallel_delegation(self, agent_names: list[str], task: str):
        import json

        tasks_json = json.dumps(
            [{"agent_name": n, "task": task} for n in agent_names],
            ensure_ascii=False,
        )
        prefix = f"[delegate_parallel] tasks={tasks_json}"
        names_str = ", ".join(f"@{n}" for n in agent_names)
        self.console.print(f"\n[bold]\u25b6 \u2192 {names_str} {task}[/bold]")
        self._stream = ""
        self._thinking_active = False
        self._rendered_up_to = 0
        self._in_code_block = False
        self._sub_agent_tasks = {}
        try:
            self.agent_ctx.iteration = 0
            await run_agent(self.agent_ctx, prefix)
        except KeyboardInterrupt:
            self._stop_live()
            self._stop_tool_live()
            self.console.print("\n[dim][interrupted][/dim]")
        except Exception as e:
            self._stop_live()
            self._stop_tool_live()
            self.console.print(f"\n[red]Error: {e}[/red]")
        self._stop_live()
        self._stop_tool_live()

    async def _handle_new_session(self):
        if getattr(self.args, "no_persist", False):
            self.console.print("[dim]Persistence disabled.[/dim]")
            return
        if not self._user:
            return
        ws = (self.args.workspace or settings.workspace).resolve()
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
        self.console.clear()
        self._print_banner()
        self.console.print(f"[dim]New session: {cv.session_id[:8]}[/dim]")

    async def _handle_sessions_list(self):
        if getattr(self.args, "no_persist", False):
            self.console.print("[dim]Persistence disabled.[/dim]")
            return
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.conversation import list_conversations

        async with async_session_factory() as db:
            convs = await list_conversations(db, self._user.id)
        if not convs:
            self.console.print("[dim]No sessions.[/dim]")
            return
        for i, c in enumerate(convs[:20], 1):
            title = c.title or "(untitled)"
            ts = c.updated_at.strftime("%m-%d %H:%M") if c.updated_at else ""
            mark = " [bold]*[/bold]" if c.id == self._conversation_id else ""
            self.console.print(f"  {i:>2}. {title}  [{ts}]{mark}")

    async def _handle_session_load(self, arg: str):
        if getattr(self.args, "no_persist", False):
            self.console.print("[dim]Persistence disabled.[/dim]")
            return
        chosen_sid = arg.strip() if arg.strip() else None
        if not chosen_sid:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.conversation import list_conversations

            async with async_session_factory() as db:
                convs = await list_conversations(db, self._user.id)
            if not convs:
                self.console.print("[dim]No sessions.[/dim]")
                return
            recent = convs[:20]
            for i, c in enumerate(recent, 1):
                title = c.title or "(untitled)"
                ts = c.updated_at.strftime("%m-%d %H:%M") if c.updated_at else ""
                mark = " [bold]*[/bold]" if c.id == self._conversation_id else ""
                self.console.print(f"  {i:>2}. {title}  [{ts}]{mark}")
            try:
                choice = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("Choice (# or session_id, Enter=cancel): ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                return
            if not choice:
                return
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(recent):
                    chosen_sid = recent[idx].session_id
                else:
                    self.console.print("[dim]Invalid.[/dim]")
                    return
            except ValueError:
                chosen_sid = choice

        cv, hist, ms = await self._load_conv(chosen_sid, self._user.id)
        if not cv:
            self.console.print("[dim]Session not found.[/dim]")
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
            await self._replace_persistence_listener()
        self.console.clear()
        self._print_banner()
        if hist:
            import json as _json

            for msg in hist:
                role = msg.get("role", "")
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if role == "user" and content:
                    self.console.print(f"[dim]\u25b6 {content}[/dim]")
                elif role == "assistant":
                    if reasoning:
                        self.console.print(Text(f"Thinking: {reasoning[:200]}", style="dim"))
                    tool_calls = msg.get("tool_calls") or []
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        args_raw = fn.get("arguments", {})
                        args = _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                        display = self._fmt_tool(fn.get("name", ""), args)
                        self.console.print(Text(f"  \u2192 {display}", style="cyan"))
                    if content:
                        self.console.print(Markdown(content))
                        self.console.print()
        user_count = sum(1 for m in hist if m.get("role") == "user")
        self.console.print(f"[dim]Loaded session {cv.session_id[:8]} ({user_count} turns, {len(hist)} messages)[/dim]")

    async def _ensure_conversation(self):
        if self._conversation_id or getattr(self.args, "no_persist", False):
            return
        ws = (self.args.workspace or settings.workspace).resolve()
        cv = await self._init_conv(self._user.id, str(ws), self.agent_ctx.model if self.agent_ctx else "")
        self._conversation_id = cv.id
        self._session_id_str = cv.session_id
        self._state = {"fm": [True]}
        if self.agent_ctx:
            self.agent_ctx.metadata["session_id"] = cv.session_id
            self.agent_ctx.metadata["branch_id"] = "main"
            await self._replace_persistence_listener()

    async def _replace_persistence_listener(self):
        if not self.agent_ctx or not self._conversation_id:
            return
        from crabagent.serve.services.persistence import PersistenceListener

        new_p = PersistenceListener(conversation_id=self._conversation_id)
        new_p.sequence = len(self.agent_ctx.messages)
        old_listeners = [
            cb
            for cb in self.agent_ctx.event_bus._listeners
            if hasattr(cb, "__self__") and isinstance(cb.__self__, PersistenceListener)
        ]
        for old in old_listeners:
            await old.__self__.finalize()
            self.agent_ctx.event_bus.unsubscribe(old)
        self.agent_ctx.event_bus.subscribe(new_p.on_event)

    def _parse_agent_mentions(self, text: str) -> tuple[list[str], str]:
        import re

        pattern = r"@(\w+)"
        matches = re.findall(pattern, text)
        clean = re.sub(r"@\w+\s*", "", text).strip()
        return matches, clean

    async def _handle_mention_delegation(self, mentions: list[str], task: str):
        from crabagent.core.agent.agents import load_agent_registry

        agents = await load_agent_registry()
        agent_names = {a["name"] for a in agents}
        valid = [m for m in mentions if m in agent_names]
        if not valid:
            self.console.print(f"[dim]Unknown agent(s): {', '.join(mentions)}[/dim]")
            return
        if not task:
            task = "(execute assigned task)"
        if len(valid) == 1:
            await self._run_delegation(valid[0], task)
        else:
            await self._run_parallel_delegation(valid, task)

    async def _build_completer(self):
        words = list(SLASH_COMMANDS)
        try:
            from crabagent.core.agent.agents import load_agent_registry

            agents = await load_agent_registry()
            for a in agents:
                words.append(f"@{a['name']}")
        except Exception:
            pass
        return WordCompleter(words, ignore_case=True, sentence=True)

    async def _initialize(self):
        from crabagent.core.database import init_db

        await init_db()
        from sqlalchemy import select

        from crabagent.core.auth_utils import hash_password
        from crabagent.core.database import User, async_session_factory

        async with async_session_factory() as db:
            r = await db.execute(select(User).where(User.username == "cli_user"))
            self._user = r.scalar_one_or_none()
            if not self._user:
                self._user = User(username="cli_user", password_hash=hash_password("cli"), role="admin", enabled=True)
                db.add(self._user)
                await db.commit()
                await db.refresh(self._user)
        if not await self._epc():
            return
        (self.args.workspace or settings.workspace).resolve()
        cid = None
        sid = None
        hist = None
        ms = 0
        if not getattr(self.args, "no_persist", False):
            if getattr(self.args, "session", None):
                cv, hist, ms = await self._load_conv(self.args.session, self._user.id)
                if cv:
                    cid = cv.id
                    sid = cv.session_id
                if cv and cv.workspace:
                    Path(cv.workspace).resolve()
                if cv and cv.model:
                    self.args.model = cv.model
        if not getattr(self.args, "model", None):
            self.args.model = settings.load_last_model()
        if not self.args.model:
            mdls = await self._fetch_models()
            if mdls:
                self.args.model = mdls[0]
                settings.save_last_model(self.args.model)
        self.agent_ctx = await self._setup_ctx(cid, hist, ms, sid)
        self._conversation_id = cid
        self._session_id_str = sid
        self._provider_display = await self._rpd()
        if self.agent_ctx and not self.agent_ctx.model and self.args.model:
            self.agent_ctx.model = self.args.model
        self._state = {"fm": [True]}

    async def _setup_ctx(self, cid, hist, ms, sid):
        for m in ["bash", "edit", "glob", "grep", "read", "web", "write"]:
            __import__(f"crabagent.core.agent.tools.{m}")
        for m in ["browser", "scheduled_task", "agent", "custom_tool"]:
            try:
                __import__(f"crabagent.core.agent.tools.{m}")
            except Exception:
                pass
        from datetime import UTC, datetime

        from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
        from crabagent.core.agent.tools import registry
        from crabagent.core.molt.tools import register_molt_tools
        from crabagent.core.todo.tools import register_todo_tools
        from crabagent.core.task.tools import register_task_tools
        from crabagent.core.mail.tools import register_mail_tools
        from crabagent.core.meeting.tools import register_meeting_tools
        from crabagent.core.tool_loader import discover_and_register_tools

        ws = (self.args.workspace or settings.workspace).resolve()
        sds = settings.skill_discovery_dirs()
        sk = discover_skills(sds)
        if sk:
            register_skill_tool(registry, sk)
        register_molt_tools(registry)
        register_todo_tools(registry)
        register_task_tools(registry)
        register_meeting_tools(registry)
        register_mail_tools(registry)

        from crabagent.core.calendar.tools import register_calendar_tools

        register_calendar_tools(registry)

        discover_and_register_tools(registry, ws)
        base_prompt = (
            f"You are CrabAgent. Today is "
            f"{datetime.now(UTC).strftime('%Y-%m-%d %A')}. "
            f"Working directory: {ws}. Be concise."
        )
        try:
            from crabagent.core.agent.agents import build_team_prompt

            team_prompt = await build_team_prompt()
            if team_prompt:
                base_prompt += "\n\n" + team_prompt
        except Exception:
            pass
        try:
            from crabagent.core.agent.agents import build_memory_prompt

            mem_prompt = await build_memory_prompt(self._user.id if self._user else 0)
            if mem_prompt:
                base_prompt += "\n\n" + mem_prompt
        except Exception:
            pass
        # Inject project memory (zero LLM cost — built from existing lessons)
        try:
            from crabagent.core.project_memory import load_project_memory

            pm = await load_project_memory(self._user.id if self._user else 0, ws)
            if pm:
                pm_prompt = pm.to_prompt()
                if pm_prompt:
                    base_prompt += "\n\n" + pm_prompt
        except Exception:
            pass
        # Inject AGENTS.md (workspace-level project rules)
        try:
            from crabagent.core.project_memory import load_agents_md

            agents_md = load_agents_md(ws)
            if agents_md:
                base_prompt += "\n\n## Project Rules (AGENTS.md)\n\n" + agents_md
        except Exception:
            pass
        ctx = AgentContext(
            workspace=ws,
            tool_registry=registry,
            max_iterations=settings.max_iterations,
            model=getattr(self.args, "model", None),
            provider_name=getattr(self.args, "provider", None),
            system_prompt=base_prompt,
        )
        if sid:
            ctx.metadata["session_id"] = sid
            ctx.metadata["branch_id"] = "main"
        if self._user and self._user.id:
            ctx.metadata["user_id"] = self._user.id
        # Attach middleware (reflect + title) so TUI benefits from lesson/preference extraction too
        try:
            from crabagent.core.agent.middlewares import MiddlewareChain
            from crabagent.core.agent.middlewares.reflect_middleware import ReflectMiddleware
            from crabagent.core.agent.middlewares.title_middleware import TitleMiddleware

            ctx.middlewares = MiddlewareChain([ReflectMiddleware(), TitleMiddleware()])
        except Exception:
            pass
        if cid and not getattr(self.args, "no_persist", False):
            from crabagent.serve.services.persistence import PersistenceListener

            p = PersistenceListener(conversation_id=cid)
            if hist:
                p.sequence = ms if ms > 0 else len(hist)
            ctx.event_bus.subscribe(p.on_event)
        if not settings.auto_approve_tools:
            ctx.confirm_callback = None
        try:
            from crabagent.core.mcp.client import MCPClientManager
            from crabagent.core.mcp.tools import register_mcp_tools

            mgr = MCPClientManager()
            await mgr.start_all()
            register_mcp_tools(ctx.tool_registry, mgr)
            ctx.metadata["_mcp_manager"] = mgr
        except Exception:
            pass
        return ctx

    async def _cleanup(self):
        if self.agent_ctx:
            for k in ["_mcp_manager", "_browser_manager"]:
                mgr = self.agent_ctx.metadata.get(k)
                if mgr:
                    try:
                        await asyncio.wait_for(mgr.stop_all() if k == "_mcp_manager" else mgr.close(), timeout=10)
                    except Exception:
                        pass

    async def _persist_user_message(self, ui):
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import save_message

        seq = len(self.agent_ctx.messages) + 1
        agent = self.agent_ctx.metadata.get("_current_agent", "default") if self.agent_ctx else "default"
        async with async_session_factory() as db:
            await save_message(
                db, conversation_id=self._conversation_id, sequence=seq, role="user", content=ui, agent=agent
            )
        if self._state.get("fm", [True])[0]:
            self._state["fm"][0] = False
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as db:
                await update_conversation(db, self._session_id_str, title=ui[:50] + ("..." if len(ui) > 50 else ""))

    @staticmethod
    async def _epc():
        from crabagent.core.provider_store import PROVIDER_CATALOG, create_provider, list_providers

        ps = await list_providers()
        if ps:
            return True
        print("\nNo LLM provider.\nAvailable:")
        for k, v in PROVIDER_CATALOG.items():
            print(f"  {k}: {v['display_name']}")
        while True:
            try:
                c = input("\nAdd one? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            if c in ("n", "no"):
                return False
            pt = input("Provider type [deepseek]: ").strip().lower() or "deepseek"
            if not PROVIDER_CATALOG.get(pt):
                continue
            nm = input(f"Name [{pt}]: ").strip() or pt
            ak = input("API key: ").strip()
            if not ak:
                continue
            try:
                await create_provider(
                    name=nm,
                    display_name=PROVIDER_CATALOG[pt]["display_name"],
                    provider_type=pt,
                    api_key=ak,
                    base_url=PROVIDER_CATALOG[pt]["base_url"],
                    is_default=True,
                )
                print("Configured.\n")
                return True
            except Exception as e:
                print(f"Error: {e}\n")

    @staticmethod
    async def _load_conv(sid, uid):
        from sqlalchemy import select

        from crabagent.core.database import Conversation, async_session_factory
        from crabagent.serve.services.message import get_messages, message_to_dict

        async with async_session_factory() as db:
            r = await db.execute(select(Conversation).where(Conversation.session_id == sid))
            cv = r.scalar_one_or_none()
            if not cv or cv.user_id != uid:
                return None, [], 0
            msgs = await get_messages(db, cv.id)
            all_dicts = [message_to_dict(m) for m in msgs if m.role != "stats"]
            user_indices = [i for i, m in enumerate(all_dicts) if m.get("role") == "user"]
            if len(user_indices) > 20:
                start = user_indices[-20]
                trimmed = all_dicts[start:]
            else:
                trimmed = all_dicts
            return (
                cv,
                trimmed,
                max((m.sequence for m in msgs), default=0),
            )

    @staticmethod
    async def _init_conv(uid, ws, mdl):
        import secrets

        from crabagent.core.database import Conversation, async_session_factory

        async with async_session_factory() as db:
            sid = secrets.token_hex(16)
            cv = Conversation(session_id=sid, user_id=uid, workspace=ws, model=mdl, title="New")
            db.add(cv)
            await db.commit()
            await db.refresh(cv)
            return cv

    @staticmethod
    async def _fetch_models(pn=None):
        from crabagent.core.provider_store import fetch_models, get_default_provider, get_provider

        try:
            p = await get_provider(pn) if pn else await get_default_provider()
            return await fetch_models(p.name) if p else []
        except Exception:
            return []

    async def _rpd(self):
        from crabagent.core.provider_store import get_default_provider, get_provider

        try:
            p = await get_provider(self.args.provider) if self.args.provider else await get_default_provider()
            if p:
                return p.name
        except Exception:
            pass
        return self.args.provider or "default"


async def run_tui(args):
    logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)

    from crabagent.core import configure_litellm

    configure_litellm()
    await TuiSession(args).run()
