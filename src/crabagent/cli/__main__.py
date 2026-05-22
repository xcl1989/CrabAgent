from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
import logging
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.config import settings
from crabagent.core.event import AgentEvent, EventType

SLASH_COMMANDS = [
    "/exit", "/quit", "/help", "/clear", "/history",
    "/model", "/models", "/provider", "/skills", "/skill",
    "/sessions", "/session", "/new", "/molt", "/todo", "/image",
]
PROVIDER_SUB = ["add", "list", "remove", "set-default"]
PROMPT_STYLE = Style.from_dict({
    "status": "#888888",
    "toolbar": "bg:#1a1a2e #888888",
})
CLI_USERNAME = "__cli__"


def main():
    parser = argparse.ArgumentParser(
        prog="crabagent",
        description="CrabAgent - AI Agent Platform",
    )
    parser.add_argument("query", nargs="?", help="Query to send to the agent")
    parser.add_argument("--workspace", "-w", type=Path, help="Workspace directory")
    parser.add_argument("--provider", "-p", help="Provider name to use")
    parser.add_argument("--model", "-m", help="Model to use")
    parser.add_argument("--session", "-s", help="Resume a session by session_id")
    parser.add_argument("--max-iterations", type=int, default=50, help="Max iterations")
    parser.add_argument("--serve", action="store_true", help="Start in serve mode")
    parser.add_argument("--host", default=settings.serve_host, help="Serve host")
    parser.add_argument("--port", type=int, default=settings.serve_port, help="Serve port")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-persist", action="store_true", help="Disable conversation persistence")

    args = parser.parse_args()
    subcmd_words = {"init", "provider", "skill", "models"}

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.serve:
        _run_serve(args)
        return

    if args.query and args.query.split()[0].lower() in subcmd_words:
        _dispatch_subcommand(args)
        return

    if not args.query:
        asyncio.run(_run_interactive(args))
    else:
        asyncio.run(_run_single(args))


def _dispatch_subcommand(args):
    remaining = args.query.split()
    subcmd = remaining[0].lower()
    if subcmd == "provider":
        _dispatch_provider(remaining[1:])
    elif subcmd == "skill":
        _dispatch_skill(remaining[1:])
    elif subcmd == "models":
        asyncio.run(_cmd_models())
    elif subcmd == "init":
        asyncio.run(_cmd_init())


def _dispatch_provider(argv: list[str]):
    from crabagent.cli.provider import main as provider_main
    provider_main(argv)


def _dispatch_skill(argv: list[str]):
    parser = argparse.ArgumentParser(prog="crabagent skill")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="List available skills")
    show_p = sub.add_parser("show", help="Show a skill")
    show_p.add_argument("name")
    args = parser.parse_args(argv)
    asyncio.run(_cmd_skill(args))


async def _cmd_skill(args):
    from crabagent.core.agent.skill.loader import discover_skills

    dirs = settings.skill_discovery_dirs()
    skills = discover_skills(dirs)

    if args.cmd == "list":
        if not skills:
            print("No skills found in:", ", ".join(str(d) for d in dirs if d.exists()))
            return
        for s in sorted(skills.values(), key=lambda x: x.name):
            aux = f" ({len(s.auxiliary_files)} files)" if s.auxiliary_files else ""
            print(f"  {s.name}{aux}")
            print(f"    {s.description}")
            print(f"    location: {s.location}")
    elif args.cmd == "show":
        skill = skills.get(args.name)
        if not skill:
            names = ", ".join(sorted(skills.keys())) if skills else "(none)"
            print(f"Skill '{args.name}' not found. Available: {names}")
            return
        from crabagent.core.agent.skill.loader import format_skill_content
        print(format_skill_content(skill))
    else:
        print("Usage: crabagent skill {list|show}")


async def _cmd_models():
    from crabagent.core.provider_store import get_default_provider
    provider = await get_default_provider()
    if not provider:
        print("No default provider configured.")
        return
    from crabagent.core.provider_store import fetch_models
    try:
        models = await fetch_models(provider.name)
        for m in models:
            print(m)
    except Exception as e:
        print(f"Error fetching models: {e}")


async def _cmd_init():
    from crabagent.core.database import init_db
    await init_db()
    print("CrabAgent initialized.")


async def _ensure_cli_user():
    from sqlalchemy import select
    from crabagent.core.database import User, async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.username == CLI_USERNAME))
        user = result.scalar_one_or_none()
        if user:
            return user
        from crabagent.serve.services.auth import hash_password

        user = User(
            username=CLI_USERNAME,
            password_hash=hash_password("cli"),
            role="user",
            enabled=True,
        )
        db.add(user)
        await db.commit()
        return user


async def _init_conversation(user_id: int, workspace: str, model: str, title: str = ""):
    from crabagent.core.database import async_session_factory
    from crabagent.serve.services.conversation import create_conversation

    async with async_session_factory() as db:
        return await create_conversation(db, user_id=user_id, workspace=workspace, model=model, title=title)


async def _load_conversation(session_id: str, user_id: int):
    from crabagent.core.database import async_session_factory
    from crabagent.serve.services.conversation import get_conversation
    from crabagent.serve.services.message import get_messages, message_to_dict

    async with async_session_factory() as db:
        conv = await get_conversation(db, session_id)
        if not conv:
            print(f"Session '{session_id}' not found.")
            return None, [], 0
        if conv.user_id != user_id:
            print(f"Session '{session_id}' not found.")
            return None, [], 0
        msgs = await get_messages(db, conv.id)
        max_seq = max((m.sequence for m in msgs), default=0)
        history = [message_to_dict(m) for m in msgs if m.role != "stats"]
        return conv, history, max_seq


def _make_cli_event_handler(console):
    thinking_started = [False]
    text_buffer = []
    live = [None]

    def _ensure_live():
        if console and not live[0]:
            from rich.live import Live
            from rich.markdown import Markdown
            live[0] = Live(Markdown(""), console=console, refresh_per_second=20, auto_refresh=True, vertical_overflow="visible")
            live[0].start()

    def _update_live(text: str):
        if not live[0]:
            return
        from rich.markdown import Markdown
        live[0].update(Markdown(text), refresh=True)

    def _stop_live():
        if live[0]:
            live[0].stop()
            live[0] = None

    def on_event(event: AgentEvent):
        if event.type == EventType.THINKING_DELTA:
            if not thinking_started[0]:
                thinking_started[0] = True
                if console:
                    console.print("Thinking: ", end="", style="dim italic", highlight=False)
                else:
                    print("Thinking: ", end="", flush=True)
            if console:
                console.print(event.data.get("text", ""), end="", style="dim", highlight=False)
            else:
                print(event.data.get("text", ""), end="", flush=True)
        elif event.type == EventType.THINKING_DONE:
            thinking_started[0] = False
            if console:
                console.print()
            else:
                print()
        elif event.type == EventType.TEXT_DELTA:
            if thinking_started[0]:
                thinking_started[0] = False
                if console:
                    console.print()
                else:
                    print()
            text_buffer.append(event.data.get("text", ""))
            if console:
                _ensure_live()
                _update_live("".join(text_buffer))
            else:
                print(event.data.get("text", ""), end="", flush=True)
        elif event.type == EventType.TEXT_DONE:
            full = "".join(text_buffer)
            text_buffer.clear()
            if not full.strip():
                print()
                return
            if not console:
                print()
                return
            _update_live(full)
            _stop_live()
        elif event.type == EventType.TOOL_CALL:
            name = event.data.get("name", "")
            call_args = event.data.get("arguments", {})
            args_str = json.dumps(call_args, ensure_ascii=False)[:100]
            if console:
                console.print(f"\n  [dim cyan]\u2192 {name}({args_str})[/dim cyan]")
            else:
                print(f"\n  \u2192 {name}({args_str})")
        elif event.type == EventType.TOOL_RESULT:
            result = event.data.get("result", "")
            if console:
                console.print(f"  [dim]\u2190 {str(result)[:200]}[/dim]")
            else:
                print(f"  \u2190 {str(result)[:200]}")
        elif event.type == EventType.AGENT_ERROR:
            err = event.data.get("error", "Unknown error")
            if console:
                console.print(f"\n[red]Error: {err}[/red]")
            else:
                print(f"\nError: {err}")
        elif event.type == EventType.BUDGET_EXHAUSTED:
            if console:
                console.print("\n[yellow]Budget exhausted, generating summary...[/yellow]")
            else:
                print("\nBudget exhausted, generating summary...")
        elif event.type == EventType.CONTEXT_COMPRESSED:
            orig = event.data.get("original_count", "?")
            comp = event.data.get("compressed_count", "?")
            if console:
                console.print(f"\n  [dim yellow]Context compressed: {orig} \u2192 {comp} messages[/dim yellow]")
            else:
                print(f"\n  Context compressed: {orig} -> {comp} messages")

    return on_event


def _make_cli_confirm_callback(console):
    async def confirm(tool_name: str, args: dict) -> bool:
        args_str = json.dumps(args, ensure_ascii=False)[:120]
        if console:
            console.print(f"\n[bold yellow]\u26a0 Tool requires permission: {tool_name}[/bold yellow]")
            console.print(f"  [dim]{args_str}[/dim]")
        else:
            print(f"\n\u26a0 Tool requires permission: {tool_name}")
            print(f"  {args_str}")
        try:
            from prompt_toolkit import prompt as pt_prompt
            answer = await asyncio.get_event_loop().run_in_executor(
                None, lambda: pt_prompt("  Allow? [y/N]: ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")
    return confirm


def _make_cli_ask_callback(console):
    async def ask(question: str, options: list[str] | None = None) -> str:
        try:
            if options:
                print(f"\n  {question}")
                for i, opt in enumerate(options, 1):
                    print(f"    {i}. {opt}")
                print(f"  Choice (1-{len(options)} or custom): ", end="", flush=True)
                answer = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input().strip()
                )
                try:
                    idx = int(answer) - 1
                    if 0 <= idx < len(options):
                        return options[idx]
                except ValueError:
                    pass
                return answer
            else:
                from prompt_toolkit import prompt as pt_prompt
                answer = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: pt_prompt(f"  {question}: ").strip()
                )
                return answer
        except (EOFError, KeyboardInterrupt):
            return ""
    return ask


def _replace_persistence_listener(context, conv_id: int, seq: int, args):
    from crabagent.serve.services.persistence import PersistenceListener

    for cb in list(context.event_bus._listeners):
        if hasattr(cb, "__self__") and isinstance(cb.__self__, PersistenceListener):
            context.event_bus.unsubscribe(cb)
            break
    if not getattr(args, "no_persist", False):
        persistence = PersistenceListener(conversation_id=conv_id)
        persistence.sequence = seq
        context.event_bus.subscribe(persistence.on_event)


async def _setup_agent_context(args, conversation_id: int | None = None, history: list[dict] | None = None, persistence_start_seq: int = 0, session_id_str: str | None = None):
    import crabagent.core.agent.tools.bash  # noqa: F401
    import crabagent.core.agent.tools.edit  # noqa: F401
    import crabagent.core.agent.tools.glob  # noqa: F401
    import crabagent.core.agent.tools.grep  # noqa: F401
    import crabagent.core.agent.tools.read  # noqa: F401
    import crabagent.core.agent.tools.web  # noqa: F401
    import crabagent.core.agent.tools.write  # noqa: F401
    from crabagent.core.agent.tools import registry as _registry

    workspace = args.workspace or settings.workspace
    workspace = workspace.resolve()

    context = AgentContext(
        workspace=workspace,
        tool_registry=_registry,
        max_iterations=args.max_iterations,
        model=getattr(args, "model", None),
        provider_name=args.provider,
        system_prompt=f"You are CrabAgent, an AI assistant. Today is {datetime.now(UTC).strftime('%Y-%m-%d %A')}. Working directory: {workspace}",
    )

    if history:
        context.messages = list(history)

    if conversation_id and session_id_str:
        context.metadata["session_id"] = session_id_str
        context.metadata["branch_id"] = "main"

    from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool

    skill_dirs = settings.skill_discovery_dirs()
    skills = discover_skills(skill_dirs)
    if skills:
        register_skill_tool(context.tool_registry, skills)
    context.metadata["_skills"] = skills

    from crabagent.core.molt.tools import register_molt_tools
    register_molt_tools(context.tool_registry)

    from crabagent.core.todo.tools import register_todo_tools
    register_todo_tools(context.tool_registry)

    from crabagent.core.tool_loader import discover_and_register_tools
    discover_and_register_tools(context.tool_registry, workspace)

    from crabagent.core.mcp.client import MCPClientManager
    from crabagent.core.mcp.tools import register_mcp_tools

    mcp_manager = MCPClientManager()
    await mcp_manager.start_all()
    register_mcp_tools(context.tool_registry, mcp_manager)
    context.metadata["_mcp_manager"] = mcp_manager

    if conversation_id and not getattr(args, "no_persist", False):
        from crabagent.serve.services.persistence import PersistenceListener

        persistence = PersistenceListener(conversation_id=conversation_id)
        if history:
            persistence.sequence = persistence_start_seq if persistence_start_seq > 0 else len(history)
        context.event_bus.subscribe(persistence.on_event)

    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    context.event_bus.subscribe(_make_cli_event_handler(console))

    if not settings.auto_approve_tools:
        context.confirm_callback = _make_cli_confirm_callback(console)

    context.ask_callback = _make_cli_ask_callback(console)

    @context.tool_registry.register(
        name="ask_question",
        description="Ask the user a question and get their response. Use when you need clarification, more information, or a decision from the user before proceeding.",
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of choices for the user to pick from",
                },
            },
            "required": ["question"],
        },
    )
    async def ask_question(question: str, options: list[str] | None = None, context=None) -> str:
        cb = getattr(context, "ask_callback", None)
        if not cb:
            return "Error: no ask callback available"
        return await cb(question, options)

    return context


async def _run_single(args):
    from crabagent.core.database import init_db

    await init_db()

    user = await _ensure_cli_user()

    ok = await _ensure_provider_configured()
    if not ok:
        sys.exit(1)

    conversation_id = None
    session_id_str = None

    if not getattr(args, "no_persist", False):
        if getattr(args, "session", None):
            conv, history, max_seq = await _load_conversation(args.session, user.id)
            if conv is None:
                sys.exit(1)
            conversation_id = conv.id
            session_id_str = conv.session_id
            if conv.workspace:
                workspace = Path(conv.workspace).resolve()
            else:
                workspace = (args.workspace or settings.workspace).resolve()
            args.workspace = workspace
        else:
            workspace = args.workspace or settings.workspace
            workspace = workspace.resolve()
            conv = await _init_conversation(user.id, workspace=str(workspace), model=args.model or "",
                                            title=args.query[:50] if len(args.query) > 50 else args.query)
            conversation_id = conv.id
            session_id_str = conv.session_id
            history = None
            max_seq = 0
    else:
        history = None
        max_seq = 0

    context = await _setup_agent_context(args, conversation_id=conversation_id, history=history, persistence_start_seq=max_seq, session_id_str=session_id_str)

    try:
        await run_agent(context, args.query)
    except KeyboardInterrupt:
        pass
    finally:
        mcp_mgr = context.metadata.get("_mcp_manager")
        if mcp_mgr:
            try:
                await mcp_mgr.stop_all()
            except Exception:
                pass

    if session_id_str:
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.conversation import update_conversation

        async with async_session_factory() as db:
            await update_conversation(db, session_id_str)


def _print_banner(context, provider: str, model: str):
    try:
        from rich.console import Console
        from rich.text import Text
        console = Console()
        t = Text("CrabAgent v0.1.0", style="bold")
        console.print(t)
    except ImportError:
        print("CrabAgent v0.1.0")

    print(f"  provider: {provider}  model: {model}")
    print(f"  workspace: {context.workspace}")
    print()


def _make_status_bar(context, provider_display: str) -> str:
    msg_count = len(context.messages)
    iters = context.iteration
    tokens_display = f"{context.total_tokens:,}" if context.total_tokens else ""
    skills_count = len(context.metadata.get("_skills", {}))
    parts = [f" C:{msg_count} I:{iters}"]
    if tokens_display:
        parts.append(f"T:{tokens_display}")
    if skills_count:
        parts.append(f"S:{skills_count}")
    return f" [{provider_display}] {' '.join(parts)} "


async def _ensure_provider_configured():
    from crabagent.core.provider_store import (
        PROVIDER_CATALOG,
        create_provider,
        list_providers,
    )

    providers = await list_providers()
    if providers:
        return True

    print("\nNo LLM provider configured. CrabAgent needs at least one provider to function.\n")
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

        ptype = input(f"Provider type [deepseek]: ").strip().lower() or "deepseek"
        catalog = PROVIDER_CATALOG.get(ptype)
        if not catalog:
            print(f"Unknown provider type '{ptype}'. Available: {', '.join(PROVIDER_CATALOG.keys())}")
            continue

        name = input(f"Name [{ptype}]: ").strip() or ptype
        api_key = input("API key: ").strip()
        if not api_key:
            print("API key is required. Please try again.")
            continue

        try:
            await create_provider(
                name=name,
                display_name=catalog["display_name"],
                provider_type=ptype,
                api_key=api_key,
                base_url=catalog["base_url"],
                is_default=True,
            )
            print(f"\nProvider '{name}' ({catalog['display_name']}) configured successfully!\n")
            return True
        except Exception as e:
            print(f"Error: {e}. Please try again.\n")


async def _run_interactive(args):
    from crabagent.core.database import init_db

    await init_db()

    user = await _ensure_cli_user()

    ok = await _ensure_provider_configured()
    if not ok:
        sys.exit(1)

    workspace = args.workspace or settings.workspace
    workspace = workspace.resolve()

    conversation_id = [None]
    session_id_str = [None]
    history = None
    max_seq = 0

    if not getattr(args, "no_persist", False):
        if getattr(args, "session", None):
            conv, history, max_seq = await _load_conversation(args.session, user.id)
            if conv is None:
                sys.exit(1)
            conversation_id[0] = conv.id
            session_id_str[0] = conv.session_id
            if conv.workspace:
                workspace = Path(conv.workspace).resolve()
            if conv.model:
                args.model = conv.model
            args.workspace = workspace
        else:
            conv = await _init_conversation(user.id, workspace=str(workspace), model=args.model or "")
            conversation_id[0] = conv.id
            session_id_str[0] = conv.session_id

    args.workspace = workspace

    if not getattr(args, "model", None):
        args.model = settings.load_last_model()
    if not args.model:
        first_models = await _fetch_models_from_provider()
        if first_models:
            args.model = first_models[0]
            settings.save_last_model(args.model)

    context = await _setup_agent_context(args, conversation_id=conversation_id[0], history=history, persistence_start_seq=max_seq, session_id_str=session_id_str[0])

    provider_display = await _resolve_provider_display(args)
    model_display = args.model or "default"
    _print_banner(context, provider_display, model_display)

    completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, sentence=True)
    session = PromptSession(history=InMemoryHistory(), completer=completer, style=PROMPT_STYLE)

    first_message = [True]

    state = {
        "conversation_id": conversation_id,
        "session_id_str": session_id_str,
        "first_message": first_message,
    }

    while True:
        status = _make_status_bar(context, provider_display)

        def _get_input():
            return session.prompt(
                [("class:toolbar", status), ("", "\n> ")],
                multiline=False,
            )

        try:
            user_input = await asyncio.get_event_loop().run_in_executor(None, _get_input)
        except (EOFError, KeyboardInterrupt):
            mcp_mgr = context.metadata.get("_mcp_manager")
            if mcp_mgr:
                try:
                    await mcp_mgr.stop_all()
                except Exception:
                    pass
            print("\nBye!")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            from rich.console import Console as _cli_console
            cli_console = _cli_console()
            should_exit = await _handle_slash_command(user_input, context, args, user, state, cli_console)
            if should_exit:
                mcp_mgr = context.metadata.get("_mcp_manager")
                if mcp_mgr:
                    try:
                        await mcp_mgr.stop_all()
                    except Exception:
                        pass
                break
            continue

        if conversation_id[0] and not getattr(args, "no_persist", False):
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.message import save_message

            seq = len(context.messages) + 1
            async with async_session_factory() as db:
                await save_message(db, conversation_id=conversation_id[0], sequence=seq, role="user", content=user_input)

            if first_message[0]:
                first_message[0] = False
                from crabagent.serve.services.conversation import update_conversation

                title = user_input[:50] + ("..." if len(user_input) > 50 else "")
                async with async_session_factory() as db:
                    await update_conversation(db, session_id_str[0], title=title)

        try:
            context.iteration = 0
            await run_agent(context, user_input)
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
        except Exception as e:
            print(f"\nError: {e}")
            continue

        if conversation_id[0]:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as db:
                await update_conversation(db, session_id_str[0], tokens=context.total_tokens)


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


async def _handle_slash_command(cmd: str, context, args, user, state: dict, console) -> bool:
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    conversation_id = state["conversation_id"]
    session_id_str = state["session_id_str"]
    first_message = state["first_message"]

    if command in ("/exit", "/quit"):
        print("Bye!")
        return True

    elif command == "/help":
        print("Commands:")
        print("  /exit, /quit           Exit the session")
        print("  /clear                 Clear conversation context")
        print("  /history               Show message count and token estimate")
        print("  /model [name]         Switch model (no arg = interactive menu)")
        print("  /models               List available models")
        print("  /provider [cmd]        Manage providers (add/remove/list/set-default)")
        print("  /skills                List available skills")
        print("  /skill <name>          Show skill content")
        print("  /sessions              List recent sessions")
        print("  /session [id]          Load a previous session (interactive if no id)")
        print("  /new                   Start a new conversation")
        print("  /molt [cmd]            List, show, or rollback molts (snapshots)")
        print("  /todo [cmd]            Manage todo list")
        print("  /image <path> [msg]    Send an image with an optional message")
        print("  /help                  Show this help")
        print("  Ctrl+C                 Interrupt current agent response")
        print("  Tab                    Autocomplete slash commands")

    elif command == "/clear":
        context.messages.clear()
        context.iteration = 0
        if conversation_id[0]:
            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.message import delete_messages

            async with async_session_factory() as db:
                await delete_messages(db, conversation_id[0])
        print("Context cleared.")

    elif command == "/history":
        user_msgs = sum(1 for m in context.messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in context.messages if m.get("role") == "assistant")
        tool_msgs = sum(1 for m in context.messages if m.get("role") == "tool")
        total_chars = sum(len(str(m.get("content", ""))) for m in context.messages)
        print(f"Messages: {len(context.messages)} total")
        print(f"  user: {user_msgs}  assistant: {assistant_msgs}  tool: {tool_msgs}")
        print(f"  ~{total_chars} chars (~{total_chars // 4} tokens estimated)")
        print(f"  iteration: {context.iteration}/{context.max_iterations}")

    elif command == "/model":
        if not arg:
            await _handle_model_menu(context)
        else:
            context.model = arg
            settings.save_last_model(arg)
            print(f"Model set to: {arg}")

    elif command == "/models":
        models = await _fetch_models_from_provider(context.provider_name)
        if not models:
            print("No models available.")
        else:
            for i, m in enumerate(models, 1):
                mark = " *" if m == context.model else ""
                print(f"  {i:>2}. {m}{mark}")

    elif command == "/provider":
        await _handle_provider_slash(arg, context)
    elif command == "/skills":
        await _handle_skills_slash()
    elif command == "/skill":
        await _handle_skill_show_slash(arg)

    elif command == "/sessions":
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.conversation import list_conversations

        async with async_session_factory() as db:
            convs = await list_conversations(db, user.id)
        if not convs:
            print("No sessions found.")
        else:
            for i, c in enumerate(convs[-20:], 1):
                title = c.title or "(untitled)"
                ts = c.updated_at.strftime("%m-%d %H:%M") if c.updated_at else ""
                mark = " *" if c.id == conversation_id[0] else ""
                print(f"  {i:>2}. {c.session_id}  {title}  [{ts}]{mark}")

    elif command == "/session":
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.conversation import list_conversations

        if arg:
            chosen_sid = arg
        else:
            async with async_session_factory() as db:
                convs = await list_conversations(db, user.id)
            if not convs:
                print("No sessions found.")
                return False
            recent = convs[:20]
            print("Recent sessions:")
            for i, c in enumerate(recent, 1):
                title = c.title or "(untitled)"
                ts = c.updated_at.strftime("%m-%d %H:%M") if c.updated_at else ""
                mark = " *" if c.id == conversation_id[0] else ""
                print(f"  {i:>2}. {title}  [{ts}]{mark}")
            choice = input("Choice (number or session_id, Enter to cancel): ").strip()
            if not choice:
                return False
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(recent):
                    chosen_sid = recent[idx].session_id
                else:
                    print("Invalid choice.")
                    return False
            except ValueError:
                chosen_sid = choice

        conv, history, max_seq = await _load_conversation(chosen_sid, user.id)
        if conv is None:
            return False
        context.messages = history
        context.iteration = 0
        context.total_tokens = conv.tokens or 0
        if conv.model:
            context.model = conv.model
            args.model = conv.model
            settings.save_last_model(conv.model)
        conversation_id[0] = conv.id
        session_id_str[0] = conv.session_id
        first_message[0] = False
        _replace_persistence_listener(context, conversation_id[0], max_seq, args)
        import os as _os
        _os.system("clear" if _os.name == "posix" else "cls")
        from rich.markdown import Markdown
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                console.print(f"\n[bold green]> {content}[/bold green]")
            elif role == "assistant":
                if content:
                    console.print(Markdown(content))
                else:
                    tool_calls = msg.get("tool_calls")
                    if tool_calls:
                        names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                        console.print(f"  [dim]\u2192 calling: {', '.join(names)}[/dim]")
            elif role == "tool":
                name = msg.get("name", "")
                result = (content or "")[:200]
                hint = "..." if len(content or "") > 200 else ""
                console.print(f"  [dim]\u2192 {name}: {result}{hint}[/dim]")
        console.print(f"\n[dim]Loaded session {conv.session_id} ({len(history)} messages)[/dim]")

    elif command == "/molt":
        from crabagent.core.database import async_session_factory
        from crabagent.core.molt.store import list_molts, get_molt as _get_molt, list_molt_files
        from crabagent.core.molt.rollback import rollback

        parts = arg.split()
        subcmd = parts[0] if parts else "list"

        if subcmd == "list":
            async with async_session_factory() as db:
                molts = await list_molts(db, session_id_str[0] if session_id_str else "", limit=20)
            if not molts:
                print("No molts for this session.")
            else:
                print(f"  {'#':>3}  {'ID':<14} {'Time':<10} {'Method':<6} {'Files':<5}  Description")
                print("  " + "-" * 70)
                for i, m in enumerate(molts, 1):
                    ts = m["created_at"][:16] if m["created_at"] else ""
                    print(f"  {i:>3}  {m['molt_id']:<14} {ts:<10} {m['method']:<6} {m['file_count']:<5}  {m['description']}")

        elif subcmd == "show":
            molt_id = parts[1] if len(parts) > 1 else ""
            if not molt_id:
                print("Usage: /molt show <molt_id>")
            else:
                files = await list_molt_files(molt_id) if molt_id else []
                if not files:
                    print(f"Molt {molt_id} not found")
                else:
                    print(f"Molt: {molt_id}")
                    diff_files = [f for f in files if f == "diff.txt"]
                    if diff_files:
                        diff_path = context.workspace.resolve() / ".crabagent" / "molts" / molt_id / "diff.txt"
                        if diff_path.exists():
                            console.print(f"\n[diff]{diff_path.read_text()[:2000]}[/diff]")

        elif subcmd == "rollback":
            molt_id = parts[1] if len(parts) > 1 else ""
            if not molt_id:
                print("Usage: /molt rollback <molt_id>")
            else:
                files = await list_molt_files(molt_id) if molt_id else []
                if not files:
                    print(f"Molt {molt_id} not found")
                else:
                    actual = [f for f in files if f != "diff.txt"]
                    print(f"Restoring {len(actual)} files from {molt_id}:")
                    for f in actual:
                        print(f"  - {f}")
                    print("Continue? [y/N] ", end="", flush=True)
                    answer = input().strip().lower()
                    if answer == "y":
                        restored = await rollback(molt_id, context.workspace.resolve())
                        print(f"\u2705 Rolled back to {molt_id} ({len(restored)} files restored)")
                    else:
                        print("Cancelled.")

        elif subcmd == "prune":
            from crabagent.core.molt.store import prune_molts
            n = await prune_molts()
            print(f"Pruned {n} old molts.")

        else:
            print("Usage: /molt {list|show|rollback|prune}")

    elif command == "/todo":
        from crabagent.core.database import async_session_factory
        from crabagent.core.todo.store import add_todo, list_todos, mark_done, delete_todo

        parts = arg.split()
        subcmd = parts[0] if parts else "list"
        sess_id = session_id_str[0] if session_id_str else ""

        if subcmd == "list":
            filter_ = parts[1] if len(parts) > 1 else "all"
            async with async_session_factory() as db:
                items = await list_todos(db, sess_id, filter_)
            if not items:
                print("No tasks.")
            else:
                for t in items:
                    mark = "\u2705" if t["done"] else "\u2b1c"
                    print(f"  {t['id']}. {mark} {t['task']}")

        elif subcmd == "add":
            task = " ".join(parts[1:])
            if not task:
                print("Usage: /todo add <task>")
            else:
                async with async_session_factory() as db:
                    t = await add_todo(db, sess_id, task)
                print(f"\u2705 Added: {t['task']} (id={t['id']})")

        elif subcmd == "done":
            if len(parts) < 2:
                print("Usage: /todo done <id>")
            else:
                async with async_session_factory() as db:
                    ok = await mark_done(db, int(parts[1]), sess_id)
                print(f"\u2705 Task {parts[1]} done." if ok else "Not found.")

        elif subcmd == "delete":
            if len(parts) < 2:
                print("Usage: /todo delete <id>")
            else:
                async with async_session_factory() as db:
                    ok = await delete_todo(db, int(parts[1]), sess_id)
                print(f"\ud83d\uddd1\ufe0f Task {parts[1]} deleted." if ok else "Not found.")

        else:
            print("Usage: /todo {list|add|done|delete}")

    elif command == "/image":
        if not arg:
            print("Usage: /image <file_path> [message]")
            print("Example: /image ~/photo.png describe this image")
            return False

        import base64
        import mimetypes
        import os

        parts = arg.split(maxsplit=1)
        file_path = os.path.expanduser(parts[0])
        message = parts[1] if len(parts) > 1 else "Please describe this image."

        if not os.path.isfile(file_path):
            print(f"File not found: {file_path}")
            return False

        file_size = os.path.getsize(file_path)
        if file_size > 5 * 1024 * 1024:
            print(f"File too large: {file_size / 1024 / 1024:.1f}MB (max 5MB)")
            return False

        mime_type = mimetypes.guess_type(file_path)[0] or "image/png"
        if not mime_type.startswith("image/"):
            print(f"Not an image file: {mime_type}")
            return False

        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        content_blocks = [
            {"type": "text", "text": message},
            {
                "type": "image_url",
                "image_url": {"url": data_url},
                "file_path": os.path.abspath(file_path),
                "mime": mime_type,
                "size_kb": file_size // 1024,
            },
        ]

        if conversation_id[0] and not getattr(args, "no_persist", False):
            import json as _json

            from crabagent.core.database import async_session_factory
            from crabagent.serve.services.message import save_message

            seq = len(context.messages) + 1
            async with async_session_factory() as db:
                await save_message(
                    db,
                    conversation_id=conversation_id[0],
                    sequence=seq,
                    role="user",
                    content=_json.dumps(content_blocks),
                    branch_id="main",
                )

            if first_message[0]:
                first_message[0] = False
                from crabagent.serve.services.conversation import update_conversation

                title = message[:50] + ("..." if len(message) > 50 else "")
                async with async_session_factory() as db:
                    await update_conversation(db, session_id_str[0], title=title)

        try:
            context.iteration = 0
            await run_agent(context, content_blocks)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as e:
            print(f"\nError: {e}")

        return False

    elif command == "/new":
        conv = await _init_conversation(user.id, workspace=str(context.workspace), model=context.model or "")
        context.messages.clear()
        context.iteration = 0
        context.total_tokens = 0
        conversation_id[0] = conv.id
        session_id_str[0] = conv.session_id
        first_message[0] = True
        _replace_persistence_listener(context, conv.id, 0, args)
        import os as _os
        _os.system("clear" if _os.name == "posix" else "cls")
        console.print(f"[dim]New session: {conv.session_id}[/dim]")

    else:
        print(f"Unknown command: {command}. Type /help for available commands.")

    return False


async def _handle_provider_slash(arg: str, context):
    from crabagent.core.provider_store import (
        PROVIDER_CATALOG,
        create_provider,
        delete_provider,
        get_default_provider,
        list_providers,
        set_default_provider,
    )

    sub_parts = arg.split(maxsplit=1) if arg else []
    subcmd = sub_parts[0].lower() if sub_parts else "list"
    subarg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        providers = await list_providers()
        if not providers:
            print("No providers configured. Use /provider add to add one.")
            return
        default = await get_default_provider()
        default_name = default.name if default else None
        for p in providers:
            mark = " [default]" if p.name == default_name else ""
            key_preview = f"{p.api_key[:8]}..." if len(p.api_key) > 8 else p.api_key
            display = p.display_name or p.name
            print(f"  {p.name} ({display}){mark}")
            print(f"    type: {p.provider_type}  key: {key_preview}")
            if p.base_url:
                print(f"    base_url: {p.base_url}")

    elif subcmd == "add":
        print("Available provider types:")
        for cat in PROVIDER_CATALOG:
            print(f"  {cat['name']} ({cat['display_name']})")
        ptype = input("Provider type: ").strip()
        name = input("Name: ").strip()
        display = input("Display name (optional): ").strip()
        api_key = input("API key: ").strip()
        base_url = input("Base URL (optional): ").strip()
        if not ptype or not name or not api_key:
            print("provider type, name, and API key are required.")
            return
        try:
            await create_provider(name=name, display_name=display or name, provider_type=ptype, api_key=api_key, base_url=base_url or "")
            print(f"Provider '{name}' added.")
        except Exception as e:
            print(f"Error: {e}")

    elif subcmd == "remove":
        if not subarg:
            print("Usage: /provider remove <name>")
            return
        await delete_provider(subarg)
        print(f"Provider '{subarg}' removed.")

    elif subcmd == "set-default":
        if not subarg:
            print("Usage: /provider set-default <name>")
            return
        await set_default_provider(subarg)
        print(f"Default provider set to '{subarg}'.")

    else:
        print("Usage: /provider {list|add|remove|set-default}")


async def _handle_model_menu(context):
    models = await _fetch_models_from_provider(context.provider_name)
    if not models:
        print("No models available.")
        return
    print("Available models:")
    for i, m in enumerate(models, 1):
        mark = " *" if m == context.model else ""
        print(f"  {i:>2}. {m}{mark}")
    try:
        choice = input("Choice (number or model name, Enter to cancel): ").strip()
        if not choice:
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                chosen = models[idx]
            else:
                print("Invalid choice.")
                return
        except ValueError:
            chosen = choice
            if chosen not in models:
                print(f"Model '{chosen}' not in list, using anyway.")
        context.model = chosen
        settings.save_last_model(chosen)
        print(f"Model set to: {chosen}")
    except (EOFError, KeyboardInterrupt):
        pass


async def _fetch_models_from_provider(provider_name: str | None = None):
    try:
        from crabagent.core.provider_store import fetch_models, get_default_provider, get_provider

        if provider_name:
            p = await get_provider(provider_name)
        else:
            p = await get_default_provider()
        if not p:
            return []
        return await fetch_models(p.name)
    except Exception:
        return []


async def _handle_skills_slash():
    from crabagent.core.agent.skill.loader import discover_skills

    dirs = settings.skill_discovery_dirs()
    skills = discover_skills(dirs)
    if not skills:
        print("No skills found.")
        return
    for s in sorted(skills.values(), key=lambda x: x.name):
        aux = f" ({len(s.auxiliary_files)} files)" if s.auxiliary_files else ""
        print(f"  {s.name}{aux}")
        print(f"    {s.description}")


async def _handle_skill_show_slash(arg: str):
    if not arg:
        print("Usage: /skill <name>")
        return
    from crabagent.core.agent.skill.loader import discover_skills, format_skill_content

    dirs = settings.skill_discovery_dirs()
    skills = discover_skills(dirs)
    skill = skills.get(arg)
    if not skill:
        names = ", ".join(sorted(skills.keys())) if skills else "(none)"
        print(f"Skill '{arg}' not found. Available: {names}")
        return
    print(format_skill_content(skill))


def _run_serve(args):
    try:
        import uvicorn
    except ImportError:
        print("Error: 'serve' mode requires additional dependencies.")
        print("Install with: pip install 'crabagent[serve]'")
        sys.exit(1)

    from crabagent.serve.app import create_app

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
