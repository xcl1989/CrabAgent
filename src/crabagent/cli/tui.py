from __future__ import annotations

import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Input, RichLog

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType

_tui_app = None


class CrabAgentTuiApp(App[None]):
    CSS = """
    RichLog {
        background: #0d1117;
        color: #e6edf3;
        scrollbar-color: #30363d;
        scrollbar-background: #0d1117;
    }
    RichLog:focus {
        border: none;
    }
    #input-container {
        dock: bottom;
        height: auto;
        padding: 1 2;
        background: #161b22;
        border-top: solid #30363d;
    }
    Input {
        background: #21262d;
        color: #e6edf3;
        border: solid #30363d;
    }
    Input:focus {
        border: solid #58a6ff;
    }
    Input>.input--placeholder {
        color: #8b949e;
    }
    """

    BINDINGS = [
        ("ctrl+backslash", "quit", "Quit"),
        ("ctrl+a", "select_all", "Select All"),
        ("escape", "focus_input", "Focus"),
    ]

    def __init__(self):
        super().__init__()
        global _tui_app
        _tui_app = self
        self.agent_ctx: AgentContext | None = None
        self._tool_buffer: dict[str, dict] = {}
        self._stream_buffer = ""
        self._thinking_active = False
        self._agent_running = False
        self._provider_display = "default"
        self._conversation_id = None
        self._session_id_str = None
        self._workspace = Path.cwd()
        self._first_message = True
        self._cli_args = None
        self._user = None
        self._state = {}
        self._exit_flag = False

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, max_lines=10000, id="output")
        with Container(id="input-container"):
            yield Input(placeholder="Type a message or /command...", id="input")

    async def on_mount(self) -> None:
        input_widget = self.query_one("#input", Input)

        await self._initialize()

        log = self.query_one("#output", RichLog)
        if self.agent_ctx:
            log.write("[bold]🦀 CrabAgent v0.5.1[/bold]")
            log.write(f"  provider: {self._provider_display}  model: {self.agent_ctx.model or 'default'}")
            log.write(f"  workspace: {self._workspace}")
            log.write("")

        self.set_interval(1, self._tick_status)
        input_widget.focus()

    def _log(self) -> RichLog:
        return self.query_one("#output", RichLog)

    async def _initialize(self):
        from crabagent.core.database import init_db
        await init_db()

        user = await self._ensure_cli_user()
        self._user = user

        ok = await self._ensure_provider_configured()
        if not ok:
            self.exit()
            return

        workspace = (self._cli_args.workspace if self._cli_args and self._cli_args.workspace else settings.workspace).resolve()
        self._workspace = workspace

        conversation_id = None
        session_id_str = None
        history = None
        max_seq = 0

        if self._cli_args and not getattr(self._cli_args, "no_persist", False):
            if getattr(self._cli_args, "session", None):
                conv, history, max_seq = await self._load_conversation(self._cli_args.session, user.id)
                if conv is None:
                    self.exit()
                    return
                conversation_id = conv.id
                session_id_str = conv.session_id
                if conv.workspace:
                    self._workspace = Path(conv.workspace).resolve()
                if conv.model:
                    self._cli_args.model = conv.model
            else:
                args_model = getattr(self._cli_args, "model", "") if self._cli_args else ""
                conv = await self._init_conversation(user.id, workspace=str(self._workspace), model=args_model or "")
                conversation_id = conv.id
                session_id_str = conv.session_id

        if self._cli_args:
            if not getattr(self._cli_args, "model", None):
                self._cli_args.model = settings.load_last_model()
            if not self._cli_args.model:
                first_models = await self._fetch_models_from_provider()
                if first_models:
                    self._cli_args.model = first_models[0]
                    settings.save_last_model(self._cli_args.model)

        self.agent_ctx = await self.setup_agent_context(
            self._cli_args, conversation_id=conversation_id,
            history=history, persistence_start_seq=max_seq,
            session_id_str=session_id_str,
        )
        self._conversation_id = conversation_id
        self._session_id_str = session_id_str

        self._provider_display = await self._resolve_provider_display(self._cli_args)
        if self.agent_ctx and not self.agent_ctx.model and hasattr(self._cli_args, "model") and self._cli_args.model:
            self.agent_ctx.model = self._cli_args.model

        self._state = {
            "conversation_id": [conversation_id],
            "session_id_str": [session_id_str],
            "first_message": [True],
        }

        self.agent_ctx.event_bus.subscribe(self._on_agent_event)

    async def _on_agent_event(self, event: AgentEvent):
        log = self._log()
        if event.type == EventType.TEXT_DELTA:
            if self._thinking_active:
                self._thinking_active = False
                log.write("")
            text = event.data.get("text", "")
            self._stream_buffer += text
            while "\n\n" in self._stream_buffer:
                para, self._stream_buffer = self._stream_buffer.split("\n\n", 1)
                log.write(para)
        elif event.type == EventType.TEXT_DONE:
            if self._stream_buffer:
                log.write(self._stream_buffer)
                self._stream_buffer = ""
            log.write("")
        elif event.type == EventType.THINKING_DELTA:
            self._thinking_active = True
            text = event.data.get("text", "")
            log.write(f"[dim italic]{text}[/dim italic]", shrink=False)
        elif event.type == EventType.THINKING_DONE:
            self._thinking_active = False
        elif event.type == EventType.AGENT_ERROR:
            err = event.data.get("error", "Unknown error")
            log.write(f"[red]Error: {err}[/red]")
        elif event.type == EventType.TOOL_CALL:
            call_id = event.data.get("id", "")
            display = self._format_tool_display(event.data.get("name", ""), event.data.get("arguments", {}))
            source = event.data.get("source", "builtin")
            self._tool_buffer[call_id] = {"display": display, "source": source, "started": time.time()}
        elif event.type == EventType.TOOL_RESULT:
            call_id = event.data.get("id", "")
            call_info = self._tool_buffer.pop(call_id, None)
            if call_info:
                prefix = "🔌 " if call_info["source"] == "mcp" else ""
                style = "bright_magenta" if call_info["source"] == "mcp" else "cyan"
                log.write(f"  [{style}]{prefix}→ {call_info['display']}[/{style}]")
                result = event.data.get("result", "")
                first_line = (result or "").split("\n")[0]
                if len(first_line) > 300:
                    first_line = first_line[:300] + "..."
                log.write(f"  [dim]← {first_line}[/dim]")
                log.write("")
        elif event.type == EventType.CONTEXT_COMPRESSED:
            orig = event.data.get("original_count", 0)
            comp = event.data.get("compressed_count", 0)
            log.write(f"[yellow]Context compressed: {orig} → {comp} messages[/yellow]")
        elif event.type == EventType.BUDGET_EXHAUSTED:
            log.write("[yellow]Budget exhausted, generating summary...[/yellow]")

    def _format_tool_display(self, name: str, args: dict) -> str:
        if name == "read" and "file_path" in args:
            return f"read {args['file_path']}"
        if name in ("write", "edit") and "file_path" in args:
            return f"{name} {args['file_path']}"
        if name == "bash" and "command" in args:
            cmd = str(args["command"])[:80]
            return f"bash {cmd}"
        if name in ("web_search", "web_scrape"):
            q = args.get("query") or args.get("url") or ""
            return f"{name} {str(q)[:60]}"
        keys = list(args.keys())
        if keys:
            val = str(args[keys[0]])[:60]
            return f"{name} {keys[0]}={val}"
        return name

    def _tick_status(self):
        if not self.agent_ctx:
            return
        msg_count = len(self.agent_ctx.messages)
        iters = self.agent_ctx.iteration
        tokens = f"{self.agent_ctx.total_tokens:,}" if self.agent_ctx.total_tokens else "0"
        tools_pending = len(self._tool_buffer)
        model = self.agent_ctx.model or "?"
        parts = [f"Messages: {msg_count}", f"Tokens: {tokens}", f"Iterations: {iters}"]
        if tools_pending:
            parts.append(f"Tools: {tools_pending}")
        info = " | ".join(parts)
        self.sub_title = f"[{self._provider_display}/{model}] {info}"

    @work(exclusive=True, thread=False)
    async def _run_agent_worker(self, user_input: str):
        if not self.agent_ctx or self._agent_running:
            return
        self._agent_running = True
        self._tool_buffer.clear()
        self._stream_buffer = ""

        self._log().write(f"[bold]▶ {user_input}[/bold]")

        try:
            self.agent_ctx.iteration = 0
            await run_agent(self.agent_ctx, user_input)
        except Exception as e:
            self._log().write(f"[red]Error: {e}[/red]")

        self._agent_running = False

        if self._conversation_id and self.agent_ctx:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as db:
                await update_conversation(db, self._session_id_str, tokens=self.agent_ctx.total_tokens)

    def action_focus_input(self):
        self.query_one("#input", Input).focus()

    def action_select_all(self):
        self._log().text_select_all()

    def action_quit(self):
        self._exit_flag = True
        if self.agent_ctx:
            mcp_mgr = self.agent_ctx.metadata.get("_mcp_manager")
            if mcp_mgr:
                try:
                    import asyncio as _a
                    _a.get_event_loop().create_task(mcp_mgr.stop_all())
                except Exception:
                    pass
            browser_mgr = self.agent_ctx.metadata.get("_browser_manager")
            if browser_mgr:
                try:
                    import asyncio as _a
                    _a.get_event_loop().create_task(browser_mgr.close())
                except Exception:
                    pass
        self.exit()

    async def on_input_submitted(self, event: Input.Submitted):
        user_input = event.value.strip()
        event.input.clear()
        if not user_input:
            return

        if user_input.startswith("/"):
            await self._handle_slash(user_input)
            return

        if self._conversation_id and not getattr(self._cli_args, "no_persist", False):
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.message import save_message

            seq = len(self.agent_ctx.messages) + 1 if self.agent_ctx else 1
            async with async_session_factory() as db:
                await save_message(db, conversation_id=self._conversation_id, sequence=seq, role="user", content=user_input)

            if self._state.get("first_message", [True])[0]:
                self._state["first_message"][0] = False
                from crabagent.serve.services.conversation import update_conversation

                title = user_input[:50] + ("..." if len(user_input) > 50 else "")
                async with async_session_factory() as db:
                    await update_conversation(db, self._session_id_str, title=title)

        self._run_agent_worker(user_input)

    async def _handle_slash(self, user_input: str):
        parts = user_input.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        log = self._log()

        if command in ("/exit", "/quit"):
            log.write("[dim]Bye![/dim]")
            self.action_quit()

        elif command in ("/export", "/ex"):
            await self._handle_export()

        elif command == "/help":
            cmds = (
                "/exit, /quit        Exit\n"
                "/export, /ex        Export conversation to .md file\n"
                "/help               Show this help\n"
                "/clear              Clear conversation context\n"
                "/history            Show message count and token estimate\n"
                "/model [name]       Switch model\n"
                "/models             List available models\n"
                "/provider [cmd]     Manage providers\n"
                "/new                Start a new conversation\n"
                "/skills             List available skills\n"
            )
            log.write(cmds)

        elif command == "/clear":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            log.clear()
            log.write("[dim]Context cleared.[/dim]")

        elif command == "/history":
            if self.agent_ctx:
                msg_count = len(self.agent_ctx.messages)
                tokens = self.agent_ctx.total_tokens or 0
                log.write(f"[dim]Messages: {msg_count}, Tokens: {tokens:,}, Iterations: {self.agent_ctx.iteration}[/dim]")

        elif command == "/models":
            models = await self._fetch_models_from_provider()
            if not models:
                log.write("[dim]No models available.[/dim]")
            else:
                for i, m in enumerate(models, 1):
                    mark = " [bold]*[/bold]" if m == (self.agent_ctx.model if self.agent_ctx else None) else ""
                    log.write(f"  {i:>2}. {m}{mark}")

        elif command == "/model":
            if not arg:
                models = await self._fetch_models_from_provider()
                if not models:
                    log.write("[dim]No models available.[/dim]")
                else:
                    for i, m in enumerate(models, 1):
                        mark = " [bold]*[/bold]" if m == (self.agent_ctx.model if self.agent_ctx else None) else ""
                        log.write(f"  {i:>2}. {m}{mark}")
            else:
                if self.agent_ctx:
                    self.agent_ctx.model = arg
                settings.save_last_model(arg)
                log.write(f"[dim]Model set to: {arg}[/dim]")

        elif command == "/provider":
            await self._handle_provider_slash(arg)

        elif command == "/skills":
            skills = self.agent_ctx.metadata.get("_skills", {}) if self.agent_ctx else {}
            if not skills:
                log.write("[dim]No skills loaded.[/dim]")
            else:
                for name in skills:
                    log.write(f"  {name}")

        elif command == "/skill":
            skills = self.agent_ctx.metadata.get("_skills", {}) if self.agent_ctx else {}
            if arg in skills:
                log.write(skills[arg])
            else:
                log.write(f"[dim]Skill '{arg}' not found.[/dim]")

        elif command == "/new":
            if self.agent_ctx:
                self.agent_ctx.messages.clear()
            log.clear()
            log.write("[dim]New conversation started.[/dim]")

        else:
            log.write(f"[dim]Unknown command: {command}[/dim]")

    async def _handle_export(self):
        log = self._log()
        if not self._conversation_id:
            log.write("[dim]No active conversation to export.[/dim]")
            return

        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import get_messages

        async with async_session_factory() as db:
            msgs = await get_messages(db, self._conversation_id)

        filename = f"crabagent-export-{self._session_id_str[:8]}.md"
        with open(filename, "w") as f:
            f.write(f"# CrabAgent Conversation\n\n")
            for m in msgs:
                role_label = {"user": "▶", "assistant": "", "tool": "  →", "sub_agent": "🤖"}.get(m.role, m.role)
                content = (m.content or "").strip()
                if content:
                    if m.role == "assistant":
                        f.write(f"{content}\n\n")
                    else:
                        f.write(f"{role_label} {content}\n\n")

        log.write(f"[dim]Exported to {filename}[/dim]")

    async def _handle_provider_slash(self, arg: str):
        from crabagent.core.provider_store import (
            PROVIDER_CATALOG, create_provider, delete_provider,
            get_default_provider, list_providers, set_default_provider,
        )
        log = self._log()
        sub_parts = arg.split(maxsplit=1) if arg else []
        subcmd = sub_parts[0].lower() if sub_parts else "list"
        subarg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if subcmd == "list":
            providers = await list_providers()
            if not providers:
                log.write("[dim]No providers configured.[/dim]")
                return
            default = await get_default_provider()
            for p in providers:
                mark = " [bold][default][/bold]" if default and p.name == default.name else ""
                log.write(f"  {p.name} ({p.display_name or p.name}){mark}")

        elif subcmd == "add":
            with self.suspend():
                print("Available provider types:")
                for key, info in PROVIDER_CATALOG.items():
                    print(f"  {key}: {info['display_name']}")
                ptype = input("Provider type: ").strip()
                name = input("Name: ").strip()
                display = input("Display name (optional): ").strip()
                api_key = input("API key: ").strip()
                base_url = input("Base URL (optional): ").strip()
                if not ptype or not name or not api_key:
                    print("Provider type, name, and API key are required.")
                    input("Press Enter to continue...")
                    return
                try:
                    existing = await list_providers()
                    is_first = len(existing) == 0
                    await create_provider(
                        name=name, display_name=display or name,
                        provider_type=ptype, api_key=api_key,
                        base_url=base_url or "", is_default=is_first,
                    )
                    print(f"Provider '{name}' added.")
                except Exception as e:
                    print(f"Error: {e}")
                input("Press Enter to continue...")

        elif subcmd == "remove":
            if not subarg:
                log.write("[dim]Usage: /provider remove <name>[/dim]")
                return
            await delete_provider(subarg)
            log.write(f"[dim]Provider '{subarg}' removed.[/dim]")

        elif subcmd == "set-default":
            if not subarg:
                log.write("[dim]Usage: /provider set-default <name>[/dim]")
                return
            await set_default_provider(subarg)
            log.write(f"[dim]Default provider set to '{subarg}'.[/dim]")

        else:
            log.write("[dim]Usage: /provider {list|add|remove|set-default}[/dim]")

    @staticmethod
    async def _ensure_cli_user():
        from sqlalchemy import select
        from crabagent.core.database import User, async_session_factory
        from crabagent.serve.services.auth import hash_password

        async with async_session_factory() as db:
            result = await db.execute(select(User).where(User.username == "cli_user"))
            user = result.scalar_one_or_none()
            if not user:
                user = User(username="cli_user", password_hash=hash_password("cli"), role="admin", enabled=True)
                db.add(user)
                await db.commit()
                await db.refresh(user)
            return user

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
                print("Cannot continue without a provider.")
                return False
            ptype = input("Provider type [deepseek]: ").strip().lower() or "deepseek"
            catalog = PROVIDER_CATALOG.get(ptype)
            if not catalog:
                print(f"Unknown provider type '{ptype}'.")
                continue
            name = input(f"Name [{ptype}]: ").strip() or ptype
            api_key = input("API key: ").strip()
            if not api_key:
                print("API key is required.")
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
                print(f"Error: {e}. Please try again.\n")

    @staticmethod
    async def _load_conversation(session_id: str, user_id: int):
        from sqlalchemy import select
        from crabagent.core.database import Conversation, async_session_factory, message_to_dict
        from crabagent.serve.services.message import get_messages

        async with async_session_factory() as db:
            result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
            conv = result.scalar_one_or_none()
            if not conv or conv.user_id != user_id:
                print(f"Session '{session_id}' not found.")
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
            session_id = secrets.token_hex(16)
            conv = Conversation(session_id=session_id, user_id=user_id, workspace=workspace, model=model, title="New Session")
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            return conv

    @staticmethod
    async def _fetch_models_from_provider(provider_name: str | None = None):
        from crabagent.core.provider_store import fetch_models, get_default_provider, get_provider

        try:
            if provider_name:
                p = await get_provider(provider_name)
            else:
                p = await get_default_provider()
            if not p:
                return []
            return await fetch_models(p.name)
        except Exception:
            return []

    @staticmethod
    async def _resolve_provider_display(args):
        try:
            from crabagent.core.provider_store import get_default_provider, get_provider
            if args.provider:
                p = await get_provider(args.provider)
            else:
                p = await get_default_provider()
            if p:
                return p.name
        except Exception:
            pass
        return args.provider or "default"

    @staticmethod
    async def setup_agent_context(args, conversation_id=None, history=None, persistence_start_seq=0, session_id_str=None):
        import crabagent.core.agent.tools.bash  # noqa: F401
        import crabagent.core.agent.tools.edit  # noqa: F401
        import crabagent.core.agent.tools.glob  # noqa: F401
        import crabagent.core.agent.tools.grep  # noqa: F401
        import crabagent.core.agent.tools.read  # noqa: F401
        import crabagent.core.agent.tools.web  # noqa: F401
        import crabagent.core.agent.tools.write  # noqa: F401
        try:
            import crabagent.core.agent.tools.browser  # noqa: F401
        except Exception:
            pass
        try:
            import crabagent.core.agent.tools.scheduled_task  # noqa: F401
        except Exception:
            pass
        try:
            import crabagent.core.agent.tools.agent  # noqa: F401
        except Exception:
            pass

        from datetime import UTC, datetime

        from crabagent.core.agent.tools import registry as tool_registry
        from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
        from crabagent.core.molt.tools import register_molt_tools
        from crabagent.core.todo.tools import register_todo_tools
        from crabagent.core.tool_loader import discover_and_register_tools

        workspace = (args.workspace or settings.workspace).resolve() if args else Path.cwd().resolve()

        skill_dirs = settings.skill_discovery_dirs()
        skills = discover_skills(skill_dirs)
        if skills:
            register_skill_tool(tool_registry, skills)

        register_molt_tools(tool_registry)
        register_todo_tools(tool_registry)
        discover_and_register_tools(tool_registry, workspace)

        model = getattr(args, "model", None) if args else None
        system_prompt = (
            f"You are CrabAgent, an AI assistant. "
            f"Today is {datetime.now(UTC).strftime('%Y-%m-%d %A')}. "
            f"Working directory: {workspace}. "
            "Be concise. Do not repeat information."
        )

        context = AgentContext(
            workspace=workspace,
            tool_registry=tool_registry,
            max_iterations=settings.max_iterations,
            model=model or None,
            provider_name=getattr(args, "provider", None) if args else None,
            system_prompt=system_prompt,
        )

        if session_id_str:
            context.metadata["session_id"] = session_id_str
            context.metadata["branch_id"] = "main"

        if conversation_id and not (args and getattr(args, "no_persist", False)):
            from crabagent.serve.services.persistence import PersistenceListener

            persistence = PersistenceListener(conversation_id=conversation_id)
            if history:
                persistence.sequence = persistence_start_seq if persistence_start_seq > 0 else len(history)
            context.event_bus.subscribe(persistence.on_event)

        if not settings.auto_approve_tools:
            context.confirm_callback = None

        try:
            from crabagent.core.mcp.client import MCPClientManager
            from crabagent.core.mcp.tools import register_mcp_tools

            mcp_manager = MCPClientManager()
            await mcp_manager.start_all()
            register_mcp_tools(context.tool_registry, mcp_manager)
            context.metadata["_mcp_manager"] = mcp_manager
        except Exception:
            pass

        return context


def get_tui_app() -> CrabAgentTuiApp | None:
    return _tui_app


async def run_textual(args):
    app = CrabAgentTuiApp()
    app._cli_args = args
    await app.run_async()
