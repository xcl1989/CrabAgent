"""CrabAgent TUI — Rich + prompt_toolkit: native terminal selection + colors."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType

PROMPT_STYLE = Style.from_dict({
    "toolbar": "bg:#161b22 #8b949e",
})

SLASH_COMMANDS = [
    "/exit", "/quit", "/help", "/clear", "/history",
    "/model", "/models", "/provider", "/skills", "/skill",
    "/export",
]


class TuiSession:
    def __init__(self, args):
        self.args = args
        self.agent_ctx: AgentContext | None = None
        self.console = Console()
        self._tool_buffer: dict[str, dict] = {}
        self._tool_results: list[str] = []
        self._thinking_active = False
        self._provider_display = "default"
        self._conversation_id = None
        self._session_id_str = None
        self._user = None
        self._state = {}
        self._live: Live | None = None
        self._full_text = ""

    async def run(self):
        await self._initialize()
        if not self.agent_ctx:
            return

        self._print_banner()
        self.agent_ctx.event_bus.subscribe(self._on_agent_event)

        completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, sentence=True)
        session = PromptSession(history=InMemoryHistory(), completer=completer, style=PROMPT_STYLE)

        while True:
            status = self._make_status_bar()
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: session.prompt([("class:toolbar", status), ("", "\n> ")], multiline=False),
                )
            except (EOFError, KeyboardInterrupt):
                await self._cleanup()
                self.console.print("\n[dim]Bye![/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                should_exit = await self._handle_slash(user_input)
                if should_exit:
                    await self._cleanup()
                    break
                continue

            if self._conversation_id and not getattr(self.args, "no_persist", False):
                await self._persist_user_message(user_input)

            try:
                self._stop_live()
                self._full_text = ""
                self._tool_results = []
                self.console.print(f"\n[bold]▶ {user_input}[/bold]")
                self.agent_ctx.iteration = 0
                await run_agent(self.agent_ctx, user_input)
                self._stop_live()
            except KeyboardInterrupt:
                self._stop_live()
                self.console.print("\n[dim][interrupted][/dim]")
                continue
            except Exception as e:
                self._stop_live()
                self.console.print(f"\n[red]Error: {e}[/red]")
                continue

            if self._conversation_id:
                from crabagent.core.database import async_session_factory
                from crabagent.serve.services.conversation import update_conversation

                async with async_session_factory() as db:
                    await update_conversation(db, self._session_id_str, tokens=self.agent_ctx.total_tokens)

    def _make_status_bar(self) -> str:
        if not self.agent_ctx:
            return ""
        msg_count = len(self.agent_ctx.messages)
        iters = self.agent_ctx.iteration
        tokens = f"{self.agent_ctx.total_tokens:,}" if self.agent_ctx.total_tokens else "0"
        tools_pending = len(self._tool_buffer)
        model = self.agent_ctx.model or "?"
        parts = [f"Messages: {msg_count}", f"Tokens: {tokens}", f"Iterations: {iters}"]
        if tools_pending:
            parts.append(f"Tools: {tools_pending}")
        info = " | ".join(parts)
        return f" [{self._provider_display}/{model}] {info} "

    def _start_live(self):
        if not self._live:
            self._live = Live(
                Markdown(""), console=self.console,
                refresh_per_second=15, auto_refresh=True,
                vertical_overflow="visible", screen=True,
            )
            self._live.start()

    def _stop_live(self):
        if self._live:
            self._live.stop()
            self._live = None

    def _update_live(self):
        if not self._live:
            return
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text

        items = []
        if self._full_text.strip():
            items.append(Markdown(self._full_text))
        for tr in self._tool_results[-20:]:
            items.append(Text(tr))

        content = Group(*items) if items else Markdown("")
        self._live.update(content, refresh=True)

    def _on_agent_event(self, event: AgentEvent):
        if event.type == EventType.TEXT_DELTA:
            if self._thinking_active:
                self._thinking_active = False
            self._full_text += event.data.get("text", "")
            self._start_live()
            self._update_live()
        elif event.type == EventType.TEXT_DONE:
            self._update_live()
        elif event.type == EventType.THINKING_DELTA:
            self._thinking_active = True
            self._full_text += event.data.get("text", "")
            self._start_live()
            self._update_live()
        elif event.type == EventType.THINKING_DONE:
            self._thinking_active = False
        elif event.type == EventType.AGENT_ERROR:
            self._tool_results.append(f"\nError: {event.data.get('error', 'Unknown error')}")
            self._update_live()
        elif event.type == EventType.TOOL_CALL:
            call_id = event.data.get("id", "")
            display = self._format_tool_display(event.data.get("name", ""), event.data.get("arguments", {}))
            source = event.data.get("source", "builtin")
            self._tool_buffer[call_id] = {"display": display, "source": source}
        elif event.type == EventType.TOOL_RESULT:
            call_id = event.data.get("id", "")
            call_info = self._tool_buffer.pop(call_id, None)
            if call_info:
                prefix = "🔌 " if call_info["source"] == "mcp" else ""
                result = event.data.get("result", "")
                first_line = (result or "").split("\n")[0]
                if len(first_line) > 300:
                    first_line = first_line[:300] + "..."
                self._tool_results.append(f"  {prefix}→ {call_info['display']}\n  ← {first_line}\n")
            self._update_live()
        elif event.type == EventType.CONTEXT_COMPRESSED:
            orig = event.data.get("original_count", 0)
            comp = event.data.get("compressed_count", 0)
            self._tool_results.append(f"Context compressed: {orig} → {comp} messages")
            self._update_live()
        elif event.type == EventType.BUDGET_EXHAUSTED:
            self._tool_results.append("Budget exhausted, generating summary...")
            self._update_live()

    def _format_tool_display(self, name: str, args: dict) -> str:
        if name == "read" and "file_path" in args:
            return f"read {args['file_path']}"
        if name in ("write", "edit") and "file_path" in args:
            return f"{name} {args['file_path']}"
        if name == "bash" and "command" in args:
            return f"bash {str(args['command'])[:80]}"
        if name in ("web_search", "web_scrape"):
            q = args.get("query") or args.get("url") or ""
            return f"{name} {str(q)[:60]}"
        keys = list(args.keys())
        if keys:
            return f"{name} {keys[0]}={str(args[keys[0]])[:60]}"
        return name

    def _print_banner(self):
        self.console.print("[bold]🦀 CrabAgent v0.5.1[/bold]")
        self.console.print(f"  provider: {self._provider_display}  model: {self.agent_ctx.model or 'default'}")
        self.console.print(f"  workspace: {self.agent_ctx.workspace}")
        self.console.print()

    async def _handle_slash(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command in ("/exit", "/quit"):
            return True

        if command == "/help":
            self.console.print(
                "/exit, /quit        Exit\n"
                "/help               Show this help\n"
                "/clear              Clear conversation context\n"
                "/history            Show message count and token\n"
                "/model [name]       Switch model\n"
                "/models             List available models\n"
                "/export             Export to .md\n"
                "/provider [cmd]     Manage providers\n"
            )

        elif command == "/clear":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            self.console.clear()
            self._print_banner()
            self.console.print("[dim]Context cleared.[/dim]")

        elif command == "/history":
            if self.agent_ctx:
                self.console.print(
                    f"[dim]Messages: {len(self.agent_ctx.messages)}, "
                    f"Tokens: {self.agent_ctx.total_tokens or 0:,}, "
                    f"Iterations: {self.agent_ctx.iteration}[/dim]"
                )

        elif command == "/models":
            models = await self._fetch_models_from_provider()
            if not models:
                self.console.print("[dim]No models available.[/dim]")
            else:
                for i, m in enumerate(models, 1):
                    mark = " [bold]*[/bold]" if m == (self.agent_ctx.model if self.agent_ctx else None) else ""
                    self.console.print(f"  {i:>2}. {m}{mark}")

        elif command == "/model":
            if not arg:
                models = await self._fetch_models_from_provider()
                if not models:
                    self.console.print("[dim]No models available.[/dim]")
                else:
                    for i, m in enumerate(models, 1):
                        mark = " [bold]*[/bold]" if m == (self.agent_ctx.model if self.agent_ctx else None) else ""
                        self.console.print(f"  {i:>2}. {m}{mark}")
            else:
                if self.agent_ctx:
                    self.agent_ctx.model = arg
                settings.save_last_model(arg)
                self.console.print(f"[dim]Model set to: {arg}[/dim]")

        elif command == "/export":
            await self._handle_export()

        elif command == "/provider":
            await self._handle_provider_slash(arg)

        elif command == "/skills":
            skills = self.agent_ctx.metadata.get("_skills", {}) if self.agent_ctx else {}
            if not skills:
                self.console.print("[dim]No skills loaded.[/dim]")
            else:
                for name in skills:
                    self.console.print(f"  {name}")

        else:
            self.console.print(f"[dim]Unknown command: {command}[/dim]")

        return False

    async def _handle_export(self):
        if not self._conversation_id:
            self.console.print("[dim]No active conversation.[/dim]")
            return
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import get_messages

        async with async_session_factory() as db:
            msgs = await get_messages(db, self._conversation_id)
        filename = f"crabagent-export-{self._session_id_str[:8]}.md"
        with open(filename, "w") as f:
            f.write("# CrabAgent Conversation\n\n")
            for m in msgs:
                content = (m.content or "").strip()
                if not content:
                    continue
                if m.role == "assistant":
                    f.write(f"{content}\n\n")
                elif m.role == "user":
                    f.write(f"▶ {content}\n\n")
                else:
                    f.write(f"{m.role}: {content[:200]}\n\n")
        self.console.print(f"[dim]Exported to {filename}[/dim]")

    async def _handle_provider_slash(self, arg: str):
        from crabagent.core.provider_store import (
            PROVIDER_CATALOG, create_provider, delete_provider,
            get_default_provider, list_providers, set_default_provider,
        )
        sub_parts = arg.split(maxsplit=1) if arg else []
        subcmd = sub_parts[0].lower() if sub_parts else "list"
        subarg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if subcmd == "list":
            providers = await list_providers()
            if not providers:
                self.console.print("[dim]No providers configured.[/dim]")
                return
            default = await get_default_provider()
            for p in providers:
                mark = " [bold][default][/bold]" if default and p.name == default.name else ""
                self.console.print(f"  {p.name} ({p.display_name or p.name}){mark}")

        elif subcmd == "add":
            print("\nAvailable provider types:")
            for key, info in PROVIDER_CATALOG.items():
                print(f"  {key}: {info['display_name']}")
            ptype = input("Provider type: ").strip()
            name = input("Name: ").strip()
            display = input("Display name (optional): ").strip()
            api_key = input("API key: ").strip()
            base_url = input("Base URL (optional): ").strip()
            if not ptype or not name or not api_key:
                print("Provider type, name, and API key are required.")
                return
            try:
                existing = await list_providers()
                await create_provider(
                    name=name, display_name=display or name,
                    provider_type=ptype, api_key=api_key,
                    base_url=base_url or "", is_default=len(existing) == 0,
                )
                print(f"Provider '{name}' added.")
            except Exception as e:
                print(f"Error: {e}")

        elif subcmd == "remove":
            if not subarg:
                self.console.print("[dim]Usage: /provider remove <name>[/dim]")
                return
            await delete_provider(subarg)
            self.console.print(f"[dim]Provider '{subarg}' removed.[/dim]")

        elif subcmd == "set-default":
            if not subarg:
                self.console.print("[dim]Usage: /provider set-default <name>[/dim]")
                return
            await set_default_provider(subarg)
            self.console.print(f"[dim]Default provider set to '{subarg}'.[/dim]")

        else:
            self.console.print("[dim]Usage: /provider {list|add|remove|set-default}[/dim]")

    async def _initialize(self):
        from crabagent.core.database import init_db
        await init_db()

        from sqlalchemy import select
        from crabagent.core.database import User, async_session_factory
        from crabagent.serve.services.auth import hash_password

        async with async_session_factory() as db:
            result = await db.execute(select(User).where(User.username == "cli_user"))
            self._user = result.scalar_one_or_none()
            if not self._user:
                self._user = User(username="cli_user", password_hash=hash_password("cli"), role="admin", enabled=True)
                db.add(self._user)
                await db.commit()
                await db.refresh(self._user)

        ok = await self._ensure_provider_configured()
        if not ok:
            return

        workspace = (self.args.workspace or settings.workspace).resolve()
        conv_id = None
        session_id = None
        history = None
        max_seq = 0

        if not getattr(self.args, "no_persist", False):
            if getattr(self.args, "session", None):
                conv, history, max_seq = await self._load_conversation(self.args.session, self._user.id)
                if conv:
                    conv_id = conv.id
                    session_id = conv.session_id
                    if conv.workspace:
                        workspace = Path(conv.workspace).resolve()
                    if conv.model:
                        self.args.model = conv.model
            else:
                conv = await self._init_conversation(self._user.id, str(workspace), self.args.model or "")
                conv_id = conv.id
                session_id = conv.session_id

        if not getattr(self.args, "model", None):
            self.args.model = settings.load_last_model()
        if not self.args.model:
            models = await self._fetch_models_from_provider()
            if models:
                self.args.model = models[0]
                settings.save_last_model(self.args.model)

        self.agent_ctx = await self._setup_context(conv_id, history, max_seq, session_id)
        self._conversation_id = conv_id
        self._session_id_str = session_id
        self._provider_display = await self._resolve_provider_display()

        if self.agent_ctx and not self.agent_ctx.model and self.args.model:
            self.agent_ctx.model = self.args.model

        self._state = {"first_message": [True]}

    async def _setup_context(self, conv_id, history, max_seq, session_id):
        import crabagent.core.agent.tools.bash  # noqa
        import crabagent.core.agent.tools.edit  # noqa
        import crabagent.core.agent.tools.glob  # noqa
        import crabagent.core.agent.tools.grep  # noqa
        import crabagent.core.agent.tools.read  # noqa
        import crabagent.core.agent.tools.web  # noqa
        import crabagent.core.agent.tools.write  # noqa
        try:
            import crabagent.core.agent.tools.browser  # noqa
        except Exception: pass
        try:
            import crabagent.core.agent.tools.scheduled_task  # noqa
        except Exception: pass
        try:
            import crabagent.core.agent.tools.agent  # noqa
        except Exception: pass

        from datetime import UTC, datetime
        from crabagent.core.agent.tools import registry as tool_registry
        from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
        from crabagent.core.molt.tools import register_molt_tools
        from crabagent.core.todo.tools import register_todo_tools
        from crabagent.core.tool_loader import discover_and_register_tools

        workspace = (self.args.workspace or settings.workspace).resolve()
        skill_dirs = settings.skill_discovery_dirs()
        skills = discover_skills(skill_dirs)
        if skills:
            register_skill_tool(tool_registry, skills)
        register_molt_tools(tool_registry)
        register_todo_tools(tool_registry)
        discover_and_register_tools(tool_registry, workspace)

        ctx = AgentContext(
            workspace=workspace,
            tool_registry=tool_registry,
            max_iterations=settings.max_iterations,
            model=getattr(self.args, "model", None) or None,
            provider_name=getattr(self.args, "provider", None),
            system_prompt=(
                f"You are CrabAgent, an AI assistant. "
                f"Today is {datetime.now(UTC).strftime('%Y-%m-%d %A')}. "
                f"Working directory: {workspace}. "
                "Be concise. Do not repeat information."
            ),
        )

        if session_id:
            ctx.metadata["session_id"] = session_id
            ctx.metadata["branch_id"] = "main"

        if conv_id and not getattr(self.args, "no_persist", False):
            from crabagent.serve.services.persistence import PersistenceListener
            persistence = PersistenceListener(conversation_id=conv_id)
            if history:
                persistence.sequence = max_seq if max_seq > 0 else len(history)
            ctx.event_bus.subscribe(persistence.on_event)

        if not settings.auto_approve_tools:
            ctx.confirm_callback = None

        try:
            from crabagent.core.mcp.client import MCPClientManager
            from crabagent.core.mcp.tools import register_mcp_tools
            mcp_manager = MCPClientManager()
            await mcp_manager.start_all()
            register_mcp_tools(ctx.tool_registry, mcp_manager)
            ctx.metadata["_mcp_manager"] = mcp_manager
        except Exception:
            pass

        return ctx

    async def _cleanup(self):
        if self.agent_ctx:
            mcp_mgr = self.agent_ctx.metadata.get("_mcp_manager")
            if mcp_mgr:
                try:
                    await asyncio.wait_for(mcp_mgr.stop_all(), timeout=10)
                except Exception: pass
            browser_mgr = self.agent_ctx.metadata.get("_browser_manager")
            if browser_mgr:
                try:
                    await browser_mgr.close()
                except Exception: pass

    async def _persist_user_message(self, user_input):
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import save_message
        seq = len(self.agent_ctx.messages) + 1
        async with async_session_factory() as db:
            await save_message(db, conversation_id=self._conversation_id, sequence=seq, role="user", content=user_input)
        if self._state.get("first_message", [True])[0]:
            self._state["first_message"][0] = False
            from crabagent.serve.services.conversation import update_conversation
            title = user_input[:50] + ("..." if len(user_input) > 50 else "")
            async with async_session_factory() as db:
                await update_conversation(db, self._session_id_str, title=title)

    @staticmethod
    async def _ensure_provider_configured():
        from crabagent.core.provider_store import PROVIDER_CATALOG, create_provider, list_providers
        providers = await list_providers()
        if providers:
            return True
        print("\nNo LLM provider configured.\n")
        print("Available provider types:")
        for key, info in PROVIDER_CATALOG.items():
            print(f"  {key}: {info['display_name']}")
        print()
        while True:
            try:
                choice = input("Would you like to add a provider now? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCannot continue without a provider.")
                return False
            if choice in ("n", "no"):
                return False
            ptype = input("Provider type [deepseek]: ").strip().lower() or "deepseek"
            catalog = PROVIDER_CATALOG.get(ptype)
            if not catalog:
                continue
            name = input(f"Name [{ptype}]: ").strip() or ptype
            api_key = input("API key: ").strip()
            if not api_key:
                continue
            try:
                await create_provider(
                    name=name, display_name=catalog["display_name"],
                    provider_type=ptype, api_key=api_key,
                    base_url=catalog["base_url"], is_default=True,
                )
                print(f"\nProvider '{name}' configured successfully!\n")
                return True
            except Exception as e:
                print(f"Error: {e}\n")

    @staticmethod
    async def _load_conversation(session_id: str, user_id: int):
        from sqlalchemy import select
        from crabagent.core.database import Conversation, async_session_factory, message_to_dict
        from crabagent.serve.services.message import get_messages
        async with async_session_factory() as db:
            result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
            conv = result.scalar_one_or_none()
            if not conv or conv.user_id != user_id:
                return None, [], 0
            msgs = await get_messages(db, conv.id)
            max_seq = max((m.sequence for m in msgs), default=0)
            history = [message_to_dict(m) for m in msgs if m.role != "stats"]
            return conv, history, max_seq

    @staticmethod
    async def _init_conversation(user_id: int, workspace: str, model: str):
        from crabagent.core.database import Conversation, async_session_factory
        import secrets
        async with async_session_factory() as db:
            sid = secrets.token_hex(16)
            conv = Conversation(session_id=sid, user_id=user_id, workspace=workspace, model=model, title="New Session")
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            return conv

    @staticmethod
    async def _fetch_models_from_provider(provider_name: str | None = None):
        from crabagent.core.provider_store import fetch_models, get_default_provider, get_provider
        try:
            p = await get_provider(provider_name) if provider_name else await get_default_provider()
            if not p:
                return []
            return await fetch_models(p.name)
        except Exception:
            return []

    async def _resolve_provider_display(self):
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
    session = TuiSession(args)
    await session.run()
