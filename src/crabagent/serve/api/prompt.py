from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.agent.tools.registry import registry
from crabagent.core.config import settings
from crabagent.core.database import User, async_session_factory, get_db
from crabagent.core.event import AgentEvent, EventType
from crabagent.serve.deps import get_current_user, get_owned_conversation
from crabagent.serve.services import conversation as conv_svc
from crabagent.serve.services.message import get_messages, message_to_dict, save_message
from crabagent.serve.services.persistence import PersistenceListener

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

try:
    import crabagent.core.agent.tools.custom_tool  # noqa: F401
except Exception:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prompt"])

_tasks: dict[str, asyncio.Task] = {}

_session_locks: dict[str, asyncio.Lock] = {}


def _save_image_temp(data_url: str) -> dict:
    import base64
    import hashlib
    import os
    import tempfile

    header, b64 = data_url.split(",", 1)
    mime = header.split(":")[1].split(";")[0]
    ext = mime.split("/")[1] if "/" in mime else "png"
    size_kb = len(b64) * 3 // 4 // 1024

    img_dir = os.path.join(tempfile.gettempdir(), "crabagent_images")
    os.makedirs(img_dir, exist_ok=True)
    h = hashlib.md5(b64.encode()).hexdigest()[:12]
    path = os.path.join(img_dir, f"{h}.{ext}")

    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))

    return {"file_path": path, "mime": mime, "size_kb": size_kb}


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_IMAGE_PATH_RE = re.compile(
    r'(?:^|[\s(])((?:/[^\s)]+)\.(?:png|jpe?g|gif|webp|bmp))(?:[\s)]|$)',
    re.IGNORECASE,
)


def _extract_local_images(message: str) -> list[dict]:
    blocks: list[dict] = []
    for match in _IMAGE_PATH_RE.finditer(message):
        path_str = match.group(1)
        if not os.path.isfile(path_str):
            continue
        ext = os.path.splitext(path_str)[1].lower()
        if ext not in _IMAGE_EXTS:
            continue
        mime = mimetypes.guess_type(path_str)[0] or "image/png"
        try:
            with open(path_str, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except OSError:
            continue
        size_kb = os.path.getsize(path_str) // 1024
        data_url = f"data:{mime};base64,{b64}"
        _save_image_temp(data_url)
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": data_url},
                "file_path": path_str,
                "mime": mime,
                "size_kb": size_kb,
            }
        )
    return blocks


class PromptRequest(BaseModel):
    message: str
    model: str | None = None
    provider: str | None = None
    images: list[str] | None = None
    agent: str | None = None
    reasoning_effort: str | None = None


@router.post("/sessions/{session_id}/prompt", status_code=status.HTTP_202_ACCEPTED)
async def prompt_async(
    session_id: str,
    req: PromptRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_owned_conversation(db, session_id, user)

    if session_id in _tasks and not _tasks[session_id].done():
        raise HTTPException(status_code=409, detail="Session is already processing a prompt")

    active_branch = conv.active_branch or "main"
    history_msgs = await get_messages(db, conv.id, branch_id=active_branch)
    user_msg_seq = max((m.sequence for m in history_msgs), default=0) + 1

    local_images = _extract_local_images(req.message)

    if req.images:
        import json as _json

        content_blocks = [{"type": "text", "text": req.message}]
        for img in req.images:
            meta = _save_image_temp(img)
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": img},
                    "file_path": meta["file_path"],
                    "mime": meta["mime"],
                    "size_kb": meta["size_kb"],
                }
            )
        content_blocks.extend(local_images)
        db_content = _json.dumps(content_blocks)
    elif local_images:
        import json as _json

        content_blocks = [{"type": "text", "text": req.message}] + local_images
        db_content = _json.dumps(content_blocks)
    else:
        db_content = req.message

    await save_message(
        db,
        conversation_id=conv.id,
        sequence=user_msg_seq,
        role="user",
        content=db_content,
        branch_id=active_branch,
    )

    workspace = Path(conv.workspace) if conv.workspace else Path.cwd()
    workspace = workspace.resolve()

    # Reuse cached system prompt if available — preserves LLM prefix cache
    if conv.system_prompt:
        base_prompt = conv.system_prompt
    else:
        base_prompt = f"You are CrabAgent, an AI assistant. Today is {datetime.now(UTC).strftime('%Y-%m-%d %A')}. Working directory: {workspace}"
        try:
            from crabagent.core.agent.agents import build_team_prompt

            team_prompt = await build_team_prompt()
            if team_prompt:
                base_prompt += "\n\n" + team_prompt
        except Exception:
            pass

        try:
            from crabagent.core.agent.agents import build_memory_prompt, inject_agent_lessons

            mem_prompt = await build_memory_prompt(user.id, query=(req.content or "")[:500])
            if mem_prompt:
                base_prompt += "\n\n" + mem_prompt
        except Exception:
            pass

        # Inject per-agent lessons for the effective agent
        try:
            effective_agent_for_lessons = req.agent or getattr(conv, "agent", None) or "default"
            base_prompt = await inject_agent_lessons(
                base_prompt,
                user_id=user.id,
                agent_name=effective_agent_for_lessons,
                task_hint=(req.content or "")[:120],
            )
        except Exception:
            pass

        # Inject project memory
        try:
            from crabagent.core.project_memory import load_project_memory

            pm = await load_project_memory(user.id, workspace)
            if pm:
                pm_prompt = pm.to_prompt()
                if pm_prompt:
                    base_prompt += "\n\n" + pm_prompt
        except Exception:
            pass

        # Inject AGENTS.md (workspace-level project rules)
        try:
            from crabagent.core.project_memory import load_agents_md

            agents_md = load_agents_md(workspace)
            if agents_md:
                base_prompt += "\n\n## Project Rules (AGENTS.md)\n\n" + agents_md
        except Exception:
            pass

        # Persist for subsequent messages in the same session
        try:
            from crabagent.serve.services.conversation import update_conversation
            async with async_session_factory() as save_db:
                await update_conversation(save_db, session_id, system_prompt=base_prompt)
        except Exception:
            pass

    context = AgentContext(
        workspace=workspace,
        tool_registry=registry,
        max_iterations=settings.max_iterations,
        model=req.model or conv.model or None,
        provider_name=req.provider,
        system_prompt=base_prompt,
    )

    if req.images or local_images:
        from crabagent.core.agent.token_limits import is_vision_model

        resolved = req.model or conv.model or ""
        if not is_vision_model(resolved):
            context.system_prompt += (
                "\n\nThe user has attached images. This model cannot view images directly. "
                "The images are saved as local files. "
                "Use available MCP tools or file analysis tools to process the images, then describe what you find."
            )

    from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool

    skill_dirs = settings.skill_discovery_dirs()
    skills = discover_skills(skill_dirs)
    if skills:
        register_skill_tool(context.tool_registry, skills)

    from crabagent.core.molt.tools import register_molt_tools

    register_molt_tools(context.tool_registry)

    from crabagent.core.todo.tools import register_todo_tools

    register_todo_tools(context.tool_registry)

    from crabagent.core.tool_loader import discover_and_register_tools

    discover_and_register_tools(context.tool_registry, workspace)

    from crabagent.core.mcp.tools import register_mcp_tools

    mcp_manager = request.app.state.mcp_manager
    register_mcp_tools(context.tool_registry, mcp_manager)
    context.metadata["mcp_status"] = mcp_manager.get_status()

    context.metadata["session_id"] = session_id
    context.metadata["branch_id"] = active_branch
    context.metadata["user_id"] = user.id
    context.metadata["reasoning_effort"] = req.reasoning_effort or settings.reasoning_effort

    effective_agent = req.agent or getattr(conv, "agent", None) or "default"
    context.current_agent = effective_agent
    context.metadata["_current_agent"] = effective_agent

    from crabagent.core.agent.agents import get_agent as _get_agent

    if effective_agent == "default":
        _default_profile = await _get_agent("__default__")
        if _default_profile:
            tp = _default_profile.get("tool_permissions", {})
            context.tool_permissions = tp if isinstance(tp, dict) else {}
    else:
        agent_def = await _get_agent(effective_agent)
        if agent_def:
            tp = agent_def.get("tool_permissions", {})
            context.tool_permissions = tp if isinstance(tp, dict) else {}

    if effective_agent != "default":
        from crabagent.core.agent.agent_switch import filter_tool_registry
        from crabagent.core.agent.agents import build_agent_switch_msg, get_agent

        agent_def = await get_agent(effective_agent)
        if agent_def:
            context.tool_registry = filter_tool_registry(
                context.tool_registry, tool_permissions=context.tool_permissions
            )
            if agent_def.get("model"):
                context.model = agent_def["model"]
            context.messages.append(build_agent_switch_msg(agent_def))
            try:
                await conv_svc.update_conversation(db, session_id, agent=effective_agent)
            except Exception:
                pass

    for msg_record in history_msgs:
        if msg_record.role == "stats":
            continue
        context.messages.append(message_to_dict(msg_record))

    persistence = PersistenceListener(conversation_id=conv.id, branch_id=active_branch)
    persistence.sequence = user_msg_seq
    context.event_bus.subscribe(persistence.on_event)

    from crabagent.core.agent.run_recorder import RunRecorder

    resolved_model = req.model or conv.model or ""
    run_recorder = RunRecorder(user_id=user.id, session_id=session_id, model=resolved_model)
    context.event_bus.subscribe(run_recorder.on_event)

    queues = request.app.state.event_queues

    _fwd_count = 0
    _fwd_last_log = time.time()
    _throttle_until: dict[str, float] = {}
    _THROTTLE_INTERVAL = 0.1
    _THROTTLED_EVENTS: set[str] = set()
    _SKIP_GLOBAL_EVENTS: set[str] = set()
    _last_stale_cleanup = time.time()

    _CRITICAL_EVENT_TYPES = {EventType.TOOL_CONFIRM_REQUEST, EventType.USER_INPUT_REQUEST}

    async def _sse_forward(event: AgentEvent):
        nonlocal _fwd_count, _fwd_last_log, _last_stale_cleanup
        _fwd_count += 1
        now = time.time()

        if event.type in _THROTTLED_EVENTS:
            if now < _throttle_until.get(event.type, 0):
                return
            _throttle_until[event.type] = now + _THROTTLE_INTERVAL

        forward_to_global = event.type not in _SKIP_GLOBAL_EVENTS
        is_critical = event.type in _CRITICAL_EVENT_TYPES

        stale = []
        for qid, entry in list(queues.items()):
            # Parse queue entry — supports old (2/3-tuple) and new (4-tuple) formats
            if isinstance(entry, tuple) and len(entry) >= 4:
                sid, critical_q, stream_q, ts = entry
            elif isinstance(entry, tuple) and len(entry) == 3:
                sid, q, ts = entry
                critical_q = stream_q = q
            elif isinstance(entry, tuple) and len(entry) == 2:
                sid, q = entry
                critical_q = stream_q = q
                ts = now
            else:
                continue

            if now - ts > 60:
                stale.append(qid)
                continue
            if sid != session_id:
                continue

            if is_critical:
                # Critical events → unbounded queue, never dropped
                await critical_q.put(event)
            else:
                try:
                    stream_q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "_sse_forward: stream queue full session=%s event=%s → dropped (TEXT_DONE will fix tail)",
                        session_id[:8],
                        event.type,
                    )

            queues[qid] = (sid, critical_q, stream_q, now)
        for qid in stale:
            queues.pop(qid, None)

        if forward_to_global:
            global_queues = getattr(request.app.state, "global_event_queues", {})
            gstale = []
            for gqid, (gq, gts) in list(global_queues.items()):
                if now - gts > 120:
                    gstale.append(gqid)
                    continue
                global_event = AgentEvent(
                    type=event.type,
                    data={
                        **event.data,
                        "session_id": event.data.get("sub_agent_id", session_id),
                    },
                    timestamp=event.timestamp,
                )
                try:
                    gq.put_nowait(global_event)
                except asyncio.QueueFull:
                    pass
            for gqid in gstale:
                global_queues.pop(gqid, None)

        if now - _fwd_last_log > 5:
            qsizes = []
            for entry in queues.values():
                if isinstance(entry, tuple) and len(entry) >= 4:
                    s, cq, sq, *_ = entry
                    if s == session_id:
                        qsizes.append(f"c={cq.qsize()}/s={sq.qsize()}")
                elif isinstance(entry, tuple) and len(entry) >= 2:
                    s, q, *_ = entry
                    if s == session_id:
                        qsizes.append(str(q.qsize()))
            logger.info(
                "_sse_forward: %d events in %.0fs session=%s queues=%d qsizes=%s",
                _fwd_count,
                now - _fwd_last_log,
                session_id[:8],
                sum(
                    1
                    for entry in queues.values()
                    if (isinstance(entry, tuple) and len(entry) >= 2 and entry[0] == session_id)
                ),
                qsizes,
            )
            _fwd_count = 0
            _fwd_last_log = now

        if now - _last_stale_cleanup > 30:
            _last_stale_cleanup = now
            await asyncio.sleep(0)

    context.event_bus.subscribe(_sse_forward)

    import base64 as _b64
    import re as _re

    async def _on_browser_screenshot(event: AgentEvent):
        if event.type != EventType.TOOL_RESULT:
            return
        name = event.data.get("name", "")
        if not name.startswith("browser_"):
            return
        result = str(event.data.get("result", "") or "")
        match = _re.search(r"([/\w]+crabagent_screenshots/[a-f0-9_]+\.png)", result)
        if not match:
            return
        path = match.group(1)
        try:
            with open(path, "rb") as f:
                b64 = _b64.b64encode(f.read()).decode()
            data_url = f"data:image/png;base64,{b64}"
        except Exception:
            return
        await context.event_bus.emit(
            AgentEvent(
                type=EventType.SCREENSHOT,
                data={"image": data_url, "tool": name},
            )
        )

    context.event_bus.subscribe(_on_browser_screenshot)

    if not settings.auto_approve_tools:
        from crabagent.serve.api.confirm import request_confirmation

        async def _serve_confirm(tool_name: str, args: dict) -> bool:
            future = await request_confirmation(context.event_bus, session_id, tool_name, args)
            try:
                return await asyncio.wait_for(future, timeout=120.0)
            except TimeoutError:
                return False

        context.confirm_callback = _serve_confirm

    from crabagent.serve.api.input import request_user_input

    async def _serve_ask(question: str, options: list[str] | None = None) -> str:
        future = await request_user_input(context.event_bus, session_id, question, options=options)
        try:
            return await asyncio.wait_for(future, timeout=300.0)
        except TimeoutError:
            return ""

    context.ask_callback = _serve_ask

    # v0.9 — attach middleware chain (compress + reflect + title)
    try:
        from crabagent.core.agent.middlewares import MiddlewareChain
        from crabagent.core.agent.middlewares.reflect_middleware import ReflectMiddleware
        from crabagent.core.agent.middlewares.title_middleware import TitleMiddleware

        context.middlewares = MiddlewareChain([ReflectMiddleware(), TitleMiddleware()])
    except Exception:
        logger.debug("Failed to attach middleware chain", exc_info=True)

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

    async def _run():
        t0 = time.time()
        try:
            if not conv.title:
                try:
                    async with async_session_factory() as title_db:
                        title = req.message[:50] + ("..." if len(req.message) > 50 else "")
                        await conv_svc.update_conversation(title_db, session_id, title=title)
                except Exception:
                    pass
            agent_query: str | list[dict]
            if req.images:
                agent_query = [{"type": "text", "text": req.message}]
                for img in req.images:
                    meta = _save_image_temp(img)
                    agent_query.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": img},
                            "file_path": meta["file_path"],
                            "mime": meta["mime"],
                            "size_kb": meta["size_kb"],
                        }
                    )
                agent_query.extend(local_images)
            elif local_images:
                agent_query = [{"type": "text", "text": req.message}] + local_images
            else:
                agent_query = req.message
            await run_agent(context, agent_query)
        except asyncio.CancelledError:
            logger.info("Agent task cancelled for session %s", session_id)
        except Exception:
            logger.exception("Agent task failed for session %s", session_id)
        finally:
            elapsed = round(time.time() - t0, 1)
            context.metadata["_run_elapsed"] = elapsed
            resolved_model = context.metadata.get("resolved_model", context.model or "")
            resolved_provider = context.metadata.get("resolved_provider", "")

            browser_mgr = context.metadata.get("_browser_manager")
            if browser_mgr:
                try:
                    await browser_mgr.close()
                except Exception:
                    pass

            stats_data = {
                "elapsed_seconds": elapsed,
                "model": resolved_model,
                "tokens": context.visible_tokens,
                "iterations": context.iteration,
            }

            import json

            await context.event_bus.emit(
                AgentEvent(
                    type=EventType.MESSAGE_CREATED,
                    data={
                        "message": {
                            "role": "stats",
                            "content": json.dumps(stats_data, ensure_ascii=False),
                        }
                    },
                )
            )

            await context.event_bus.emit(
                AgentEvent(
                    type=EventType.AGENT_END,
                    data=stats_data,
                )
            )

            await persistence.finalize()

            _tasks.pop(session_id, None)
            _session_locks.pop(session_id, None)
            request.app.state.active_agents.pop(session_id, None)

            try:
                async with async_session_factory() as update_db:
                    await conv_svc.update_conversation(
                        update_db, session_id,
                        model=resolved_model, provider=resolved_provider,
                    )
            except Exception:
                logger.exception("Failed to update conversation")

    task = asyncio.create_task(_run())
    _tasks[session_id] = task

    request.app.state.active_agents[session_id] = {
        "user_id": user.id,
        "model": req.model or conv.model or "",
        "status": "running",
        "started_at": time.time(),
    }

    return {"status": "processing", "session_id": session_id}


@router.post("/sessions/{session_id}/abort")
async def abort_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_conversation(db, session_id, user)

    task = _tasks.get(session_id)
    if not task or task.done():
        raise HTTPException(status_code=404, detail="No running task for this session")

    task.cancel()
    return {"status": "aborted", "session_id": session_id}
