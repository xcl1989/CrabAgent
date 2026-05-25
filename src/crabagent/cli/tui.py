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
    "/delegate",
    "/new",
    "/sessions",
    "/session",
    "/skills",
    "/skill",
    "/export",
]


class TuiSession:
    def __init__(self, args):
        self.args = args
        self.agent_ctx: AgentContext | None = None
        self.console = Console()
        self._tool_buffer: dict[str, dict] = {}
        self._live: Live | None = None
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

    async def run(self):
        await self._initialize()
        if not self.agent_ctx:
            return
        self._print_banner()
        self.agent_ctx.event_bus.subscribe(self._on_agent_event)
        completer = await self._build_completer()
        session = PromptSession(history=InMemoryHistory(), completer=completer, style=PROMPT_STYLE)
        while True:
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
            await self._ensure_conversation()
            if self._conversation_id and not getattr(self.args, "no_persist", False):
                await self._persist_user_message(ui)
            self.console.print()
            self._stream = ""
            self._thinking_active = False
            self._rendered_up_to = 0
            self._in_code_block = False
            self._sub_agent_tasks = {}
            try:
                self.agent_ctx.iteration = 0
                await run_agent(self.agent_ctx, ui)
            except KeyboardInterrupt:
                self._stop_live()
                self._stop_tool_live()
                self.console.print("\n[dim][interrupted][/dim]")
                continue
            except Exception as e:
                self._stop_live()
                self._stop_tool_live()
                self.console.print(f"\n[red]Error: {e}[/red]")
                continue
            self._stop_live()
            self._stop_tool_live()
            if self._conversation_id:
                from crabagent.core.database import async_session_factory
                from crabagent.serve.services.conversation import update_conversation

                async with async_session_factory() as db:
                    await update_conversation(db, self._session_id_str, tokens=self.agent_ctx.total_tokens)

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

    def _find_paragraph_boundary(self, text):
        in_code = self._in_code_block
        last_boundary = 0
        i = 0
        while i < len(text):
            if text[i:i + 3] == "```":
                in_code = not in_code
                i += 3
                continue
            if not in_code and i + 1 < len(text) and text[i] == "\n" and text[i + 1] == "\n":
                last_boundary = i + 2
            elif not in_code and text[i] == "\n" and last_boundary == 0:
                last_boundary = i + 1
            i += 1
        return last_boundary

    def _flush_completed_paragraphs(self):
        content = self._stream[self._rendered_up_to:]
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
        if self._stream[self._rendered_up_to:]:
            self._start_spinner()

    def _stop_tool_live(self):
        self._tool_buffer.clear()

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
            remaining = self._stream[self._rendered_up_to:]
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
                "text": "",
                "tools": 0,
            }
            self.console.print(
                f"  [bold cyan]\u25b6 {display}[/bold cyan] [dim]starting: {task[:60]}[/dim]"
            )
            self._start_spinner()
        elif event.type == EventType.SUB_AGENT_TEXT_DELTA:
            sub_id = event.data.get("sub_agent_id", "")
            text = event.data.get("text", "")
            role = event.data.get("role", "")
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["text"] += text
                if role == "thinking":
                    self._sub_agent_tasks.setdefault(sub_id, {}).setdefault("_thinking", []).append(text)
        elif event.type == EventType.SUB_AGENT_TOOL_CALL:
            sub_id = event.data.get("sub_agent_id", "")
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["tools"] += 1
        elif event.type == EventType.SUB_AGENT_TOOL_RESULT:
            pass
        elif event.type == EventType.SUB_AGENT_END:
            self._stop_live()
            sub_id = event.data.get("sub_agent_id", "")
            display = event.data.get("display_name", "?")
            elapsed = event.data.get("elapsed", 0)
            tokens = event.data.get("tokens", 0)
            iterations = event.data.get("iterations", 0)
            result = event.data.get("result", "")
            tools = self._sub_agent_tasks.get(sub_id, {}).get("tools", 0)
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "done"
            tok_str = f"{tokens:,}" if tokens else "0"
            self.console.print(
                f"  [bold green]\u2713 {display}[/bold green] [dim]({elapsed}s, {tok_str} tok, {iterations} steps, {tools} tools)[/dim]"
            )
            if result:
                self.console.print(Markdown(result))
        elif event.type == EventType.SUB_AGENT_ERROR:
            self._stop_live()
            sub_id = event.data.get("sub_agent_id", "")
            agent_name = event.data.get("agent_name", "?")
            error = event.data.get("error", "unknown error")
            if sub_id in self._sub_agent_tasks:
                self._sub_agent_tasks[sub_id]["status"] = "error"
            self.console.print(
                f"  [bold red]\u2717 {agent_name}[/bold red] [red]Error: {error}[/red]"
            )

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
            f"[bold]CrabAgent v0.5.2[/bold]\n  provider: {self._provider_display}  model: {self.agent_ctx.model or 'default'}\n  workspace: {self.agent_ctx.workspace}\n"
        )

    async def _handle_slash(self, ui: str) -> bool:
        p = ui.split(maxsplit=1)
        cmd = p[0].lower()
        arg = p[1].strip() if len(p) > 1 else ""
        if cmd in ("/exit", "/quit"):
            return True
        if cmd == "/help":
            self.console.print(
                "/exit /quit  Exit\n/help  Help\n/clear  Clear\n"
                "/history  Stats\n/model [n]  Switch\n/models  List\n"
                "/new  New session\n/sessions  List\n/session [id]  Load\n"
                "/export  \u2192 .md\n/provider  Manage\n"
                "/agents  Agent team\n/delegate [@agent] [task]  Delegate\n"
            )
        elif cmd == "/clear":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            self.console.clear()
            self._print_banner()
        elif cmd == "/history":
            if self.agent_ctx:
                self.console.print(
                    f"[dim]M: {len(self.agent_ctx.messages)} T: {self.agent_ctx.total_tokens or 0:,} I: {self.agent_ctx.iteration}[/dim]"
                )
        elif cmd == "/models":
            ms = await self._fetch_models()
            if ms:
                for i, m in enumerate(ms, 1):
                    self.console.print(
                        f"  {i:>2}. {m}{' [bold]*[/bold]' if m == (self.agent_ctx.model if self.agent_ctx else None) else ''}"
                    )
            else:
                self.console.print("[dim]No models.[/dim]")
        elif cmd == "/model":
            if not arg:
                ms = await self._fetch_models()
                if ms:
                    for i, m in enumerate(ms, 1):
                        self.console.print(
                            f"  {i:>2}. {m}{' [bold]*[/bold]' if m == (self.agent_ctx.model if self.agent_ctx else None) else ''}"
                        )
                else:
                    self.console.print("[dim]No models.[/dim]")
            else:
                if self.agent_ctx:
                    self.agent_ctx.model = arg
                settings.save_last_model(arg)
                self.console.print(f"[dim]Model: {arg}[/dim]")
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
        else:
            self.console.print(f"[dim]Unknown: {cmd}[/dim]")
        return False

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
                self.console.print(
                    f"  {p.name} ({p.display_name or p.name}){' [bold][default][/bold]' if d and p.name == d.name else ''}"
                )
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
                self.console.print(
                    f"  {icon} [bold]{a.display_name or a.name}[/bold]{default_tag} {status}{model_tag}"
                )
                self.console.print(f"    [dim]Role: {a.role}[/dim]")
                self.console.print(f"    [dim]Goal: {a.goal[:80]}[/dim]")

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

            from sqlalchemy import select

            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            try:
                async with async_session_factory() as db:
                    existing = await db.execute(
                        select(AgentProfile).where(AgentProfile.name == name)
                    )
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
            from sqlalchemy import select

            from crabagent.core.agent.agents import invalidate_cache
            from crabagent.core.database import AgentProfile, async_session_factory

            async with async_session_factory() as db:
                result = await db.execute(
                    select(AgentProfile).where(AgentProfile.name == sa)
                )
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

            async with async_session_factory() as db:
                result = await db.execute(
                    select(AgentProfile).where(AgentProfile.name == sa)
                )
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
                result = await db.execute(
                    select(AgentProfile).where(AgentProfile.name == sa)
                )
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
                result = await db.execute(
                    select(AgentProfile).where(AgentProfile.name == sa)
                )
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
            task = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("Task: ").strip()
            )
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
        cv = await self._init_conv(
            self._user.id, str(ws), self.agent_ctx.model if self.agent_ctx else ""
        )
        self._conversation_id = cv.id
        self._session_id_str = cv.session_id
        self._state = {"fm": [True]}
        if self.agent_ctx:
            self.agent_ctx.messages.clear()
            self.agent_ctx.iteration = 0
            self.agent_ctx.total_tokens = 0
            self.agent_ctx.metadata["session_id"] = cv.session_id
            self.agent_ctx.metadata["branch_id"] = "main"
            self._replace_persistence_listener()
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
            self._replace_persistence_listener()
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
        self.console.print(
            f"[dim]Loaded session {cv.session_id[:8]} "
            f"({user_count} turns, {len(hist)} messages)[/dim]"
        )

    async def _ensure_conversation(self):
        if self._conversation_id or getattr(self.args, "no_persist", False):
            return
        ws = (self.args.workspace or settings.workspace).resolve()
        cv = await self._init_conv(
            self._user.id, str(ws), self.agent_ctx.model if self.agent_ctx else ""
        )
        self._conversation_id = cv.id
        self._session_id_str = cv.session_id
        self._state = {"fm": [True]}
        if self.agent_ctx:
            self.agent_ctx.metadata["session_id"] = cv.session_id
            self.agent_ctx.metadata["branch_id"] = "main"
            self._replace_persistence_listener()

    def _replace_persistence_listener(self):
        if not self.agent_ctx or not self._conversation_id:
            return
        from crabagent.serve.services.persistence import PersistenceListener

        new_p = PersistenceListener(conversation_id=self._conversation_id)
        new_p.sequence = len(self.agent_ctx.messages)
        old_listeners = [
            cb for cb in self.agent_ctx.event_bus._listeners
            if hasattr(cb, "__self__") and isinstance(cb.__self__, PersistenceListener)
        ]
        for old in old_listeners:
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

        from crabagent.core.database import User, async_session_factory
        from crabagent.serve.services.auth import hash_password

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
        ws = (self.args.workspace or settings.workspace).resolve()
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
                    ws = Path(cv.workspace).resolve()
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
        for m in ["browser", "scheduled_task", "agent"]:
            try:
                __import__(f"crabagent.core.agent.tools.{m}")
            except Exception:
                pass
        from datetime import UTC, datetime

        from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
        from crabagent.core.agent.tools import registry
        from crabagent.core.molt.tools import register_molt_tools
        from crabagent.core.todo.tools import register_todo_tools
        from crabagent.core.tool_loader import discover_and_register_tools

        ws = (self.args.workspace or settings.workspace).resolve()
        sds = settings.skill_discovery_dirs()
        sk = discover_skills(sds)
        if sk:
            register_skill_tool(registry, sk)
        register_molt_tools(registry)
        register_todo_tools(registry)
        discover_and_register_tools(registry, ws)
        base_prompt = f"You are CrabAgent. Today is {datetime.now(UTC).strftime('%Y-%m-%d %A')}. Working directory: {ws}. Be concise."
        try:
            from crabagent.core.agent.agents import build_team_prompt
            team_prompt = await build_team_prompt()
            if team_prompt:
                base_prompt += "\n\n" + team_prompt
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
        async with async_session_factory() as db:
            await save_message(db, conversation_id=self._conversation_id, sequence=seq, role="user", content=ui)
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
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    await TuiSession(args).run()
