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

try:
    import crabagent.core.agent.tools.office  # noqa: F401
except Exception:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prompt"])

_tasks: dict[str, asyncio.Task] = {}

_session_locks: dict[str, asyncio.Lock] = {}


def _should_continue_goal(snapshot: dict | None, metadata: dict) -> bool:
    """Only continue healthy goal turns; failures require user intervention."""
    return bool(
        snapshot
        and snapshot.get("status") == "active"
        and snapshot.get("auto_continue")
        and not metadata.get("_run_error")
        and not metadata.get("_agent_error")
    )


def _goal_continuation_request(request: PromptRequest) -> PromptRequest:
    """Keep the selected execution settings for an automatic Goal turn."""
    return PromptRequest(
        message=(
            "Continue the active goal from the latest checkpoint. Work on the next "
            "concrete unfinished step, then record progress or verified completion."
        ),
        model=request.model,
        provider=request.provider,
        agent=request.agent,
        reasoning_effort=request.reasoning_effort,
        file_context=request.file_context,
        workspace_type=request.workspace_type,
        work_mode=request.work_mode,
    )


MERMAID_GENERATION_INSTRUCTIONS = """\
Mermaid reliability rules:
- Generate Mermaid only when it materially improves the response; otherwise use ordinary Markdown.
- For flowcharts, use the conservative syntax `flowchart LR` or `flowchart TD`.
  Give every node a simple ASCII identifier and quote every label:
  `A["Label"]` and `Q{"Question?"}`.
- Label every branch only with the pipe form: `Q -->|Yes| A`. Never use the ambiguous `-- label -->` form.
- Keep node and edge labels as plain text. Do not use HTML (including `<br/>`),
  Markdown, URLs, HTML entities, unescaped quotes, or Mermaid styling/directive
  syntax in labels. Prefer a semicolon or separate node instead of a line break.
- Avoid parser-sensitive punctuation in labels where possible, especially brackets,
  braces, parentheses, colons, and quotation marks. If exact wording needs it,
  simplify the wording rather than using unquoted labels.
- Before sending the answer, visually inspect every Mermaid block for balanced
  brackets/quotes and ensure all edges use a supported diagram-specific form.

Safe flowchart example:
```mermaid
flowchart LR
  A["Start"] --> B["Check version"]
  B --> C{"Update available?"}
  C -->|No| D["Stay current"]
  C -->|Yes| E["Show update notice"]
```
"""


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
    r"(?:^|[\s(])((?:/[^\s)]+)\.(?:png|jpe?g|gif|webp|bmp))(?:[\s)]|$)",
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
    file_context: str = ""
    workspace_type: str = ""
    work_mode: bool = False


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

    # Determine locale early for agent switch messages
    locale = getattr(user, "locale", None) or settings.language or "en"

    # --- Determine effective agent and whether a switch message is needed ---
    effective_agent = req.agent or getattr(conv, "agent", None) or "default"

    last_agent = "default"
    for m in reversed(history_msgs):
        if m.role == "stats":
            continue
        agent = getattr(m, "agent", None) or "default"
        if agent != "default":
            last_agent = agent
            break

    agent_changed = last_agent != effective_agent

    # If agent changed, persist agent_switch BEFORE the user message
    if agent_changed and effective_agent != "default":
        from crabagent.core.agent.agents import build_agent_switch_msg, get_agent

        agent_profile = await get_agent(effective_agent)
        if agent_profile:
            switch_msg = build_agent_switch_msg(agent_profile, locale=locale)
            switch_seq = user_msg_seq
            await save_message(
                db,
                conversation_id=conv.id,
                sequence=switch_seq,
                role="agent_switch",
                content=switch_msg["content"],
                agent=effective_agent,
                branch_id=active_branch,
            )
            user_msg_seq += 1  # make room for the user message
    elif agent_changed and effective_agent == "default":
        # Switching from a specific agent back to default
        from crabagent.core.agent.agents import build_agent_switch_msg, get_agent

        default_profile = await get_agent("__default__")
        if default_profile:
            switch_msg = build_agent_switch_msg(default_profile, locale=locale)
            switch_seq = user_msg_seq
            await save_message(
                db,
                conversation_id=conv.id,
                sequence=switch_seq,
                role="agent_switch",
                content=switch_msg["content"],
                agent="default",
                branch_id=active_branch,
            )
            user_msg_seq += 1

    if agent_changed:
        try:
            await conv_svc.update_conversation(db, session_id, agent=effective_agent)
        except Exception:
            pass

    # --- Workspace context switch (same pattern as agent_switch) ---
    _work_changed = (
        req.work_mode
        and req.file_context
        and (req.file_context != (conv.current_file or "") or req.workspace_type != (conv.workspace_type or ""))
    )
    if _work_changed:
        file_name = req.file_context.split("/")[-1]
        _type_labels = {
            "document": "Office 文档",
            "code": "代码文件",
            "prototype": "原型/HTML",
            "markdown": "Markdown 文档",
        }
        _type_label = _type_labels.get(req.workspace_type, "文件")
        _hints = {
            "document": (
                "用户正在编辑此 Office 文档。使用 office_edit 工具修改时无需指定文件路径。\n"
                "⚠️ 每次修改文档后，请在回复中用「📝 变更摘要：」开头总结你做了哪些更改。"
            ),
            "code": "用户正在编辑此代码文件。",
            "prototype": "用户正在编辑此 HTML 原型，右侧有实时预览。",
            "markdown": "用户正在编辑此 Markdown 文档。",
        }
        _hint = _hints.get(req.workspace_type, "用户正在编辑此文件。")
        ws_content = f"📎 [工作区切换] {_type_label}: {file_name}\n路径: {req.file_context}\n{_hint}"
        ws_seq = user_msg_seq
        await save_message(
            db,
            conversation_id=conv.id,
            sequence=ws_seq,
            role="workspace",
            content=ws_content,
            branch_id=active_branch,
        )
        user_msg_seq += 1
        # Persist current file for next-change detection
        try:
            await conv_svc.update_conversation(
                db,
                session_id,
                current_file=req.file_context,
                workspace_type=req.workspace_type,
            )
        except Exception:
            pass

    # --- Build content & save user message (with updated seq if switch was inserted) ---
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

    saved_msg = await save_message(
        db,
        conversation_id=conv.id,
        sequence=user_msg_seq,
        role="user",
        content=db_content,
        branch_id=active_branch,
    )
    _pending_fts_id = saved_msg.id

    # Index outside the request path; search catch-up will retry it after a restart.
    try:
        from crabagent.core.fts import index_message

        asyncio.create_task(index_message(_pending_fts_id, db_content))
    except Exception:
        pass

    workspace = Path(conv.workspace) if conv.workspace else Path.cwd()
    workspace = workspace.resolve()

    # Reuse cached system prompt if available — preserves LLM prefix cache
    # Also check if prompt contains locale instruction (for migration from old cache)
    _use_cache = False
    if conv.system_prompt:
        _use_cache = True
        if locale != "en":
            from crabagent.core.i18n import get_locale_instruction

            lang_inst = get_locale_instruction(locale)
            if lang_inst and lang_inst not in conv.system_prompt:
                _use_cache = False
                logger.info(
                    "[CACHE] Session %s: MISS (old cache without locale instruction, current locale='%s')",
                    session_id,
                    locale,
                )
        if _use_cache:
            base_prompt = conv.system_prompt
            logger.info(
                "[CACHE] Session %s: HIT (prompt_len=%d, prompt_locale='%s', current locale='%s')",
                session_id,
                len(conv.system_prompt),
                getattr(conv, "prompt_locale", ""),
                locale,
            )

    if not _use_cache:
        logger.info(
            "[CACHE] Session %s: MISS (prompt_locale='%s', current locale='%s')",
            session_id,
            getattr(conv, "prompt_locale", ""),
            locale,
        )
        from crabagent.core.i18n import get_system_prompt_template

        template = get_system_prompt_template(locale)
        if template:
            now = datetime.now(UTC)
            from crabagent.core.i18n import _WEEKDAY_NAMES

            weekday = _WEEKDAY_NAMES.get(locale, {}).get(now.weekday(), now.strftime("%A"))
            base_prompt = template.format(
                date=now.strftime("%Y-%m-%d"),
                weekday=weekday,
                workspace=workspace,
            )
        else:
            now = datetime.now(UTC)
            base_prompt = (
                f"You are CrabAgent, an AI assistant. "
                f"Today is {now.strftime('%Y-%m-%d %A')}. "
                f"Working directory: {workspace}"
            )
        try:
            from crabagent.core.agent.agents import build_team_prompt

            team_prompt = await build_team_prompt(locale=locale)
            if team_prompt:
                base_prompt += "\n\n" + team_prompt
        except Exception:
            pass

        try:
            from crabagent.core.agent.agents import build_memory_prompt

            mem_prompt = await build_memory_prompt(
                user.id,
                query=(req.message or "")[:500],
                locale=locale,
                workspace_path=str(workspace),
            )
            if mem_prompt:
                base_prompt += "\n\n" + mem_prompt
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
            from crabagent.core.i18n import t
            from crabagent.core.project_memory import load_agents_md

            agents_md = load_agents_md(workspace, locale=locale)
            if agents_md:
                section_title = t("agents_md.section_title", locale)
                base_prompt += f"\n\n{section_title}\n\n" + agents_md
        except Exception:
            pass

        # Append locale instruction to the cached prompt (single system message)
        try:
            from crabagent.core.i18n import get_locale_instruction

            lang_inst = get_locale_instruction(locale)
            if lang_inst:
                base_prompt += "\n\n" + lang_inst
        except Exception:
            pass

        # Persist for subsequent messages in the same session
        try:
            from crabagent.serve.services.conversation import update_conversation

            async with async_session_factory() as save_db:
                await update_conversation(save_db, session_id, system_prompt=base_prompt, prompt_locale=locale)
            logger.info(
                "[CACHE] Session %s: SAVED (prompt_len=%d, prompt_locale='%s')", session_id, len(base_prompt), locale
            )
        except Exception as e:
            logger.warning("[CACHE] Session %s: SAVE FAILED: %s", session_id, e)

    context = AgentContext(
        workspace=workspace,
        tool_registry=registry.clone(),
        max_iterations=settings.max_iterations,
        model=req.model or conv.model or None,
        # Preserve the conversation provider if a Goal request omits it.
        provider_name=req.provider or conv.provider or None,
        system_prompt=base_prompt,
        locale=locale,
    )
    context.metadata["locale"] = locale
    try:
        from crabagent.core.goals.service import get_current_goal, goal_prompt
        from crabagent.core.goals.tools import register_goal_tools

        active_goal = await get_current_goal(db, session_id)
        if active_goal:
            context.metadata["goal_id"] = active_goal.id
            context.system_prompt += goal_prompt(active_goal)
            register_goal_tools(context, session_id, user.id)
            if active_goal.execution_model:
                context.model = active_goal.execution_model
            if active_goal.execution_provider:
                context.provider_name = active_goal.execution_provider
            if active_goal.reasoning_effort:
                context.metadata["reasoning_effort"] = active_goal.reasoning_effort
    except Exception:
        logger.exception("Failed to attach active goal for session %s", session_id)
    context.system_prompt += (
        """

## Rich response visualizations
When a visualization would improve the answer, use a fenced Markdown code block only.
- Use ```mermaid for flowcharts, sequence diagrams, state diagrams, ER diagrams,
  and architecture relationships. Follow the Mermaid reliability rules below exactly.
- Use ```crab-chart for data charts with JSON: version must be 1; type is bar, line,
  area, pie, or scatter; include x.field, data, and series. Example:
  {"version":1,"type":"bar","title":"Monthly revenue",
  "x":{"field":"month","label":"Month"},
  "series":[{"field":"revenue","name":"Revenue"}],
  "data":[{"month":"Jan","revenue":120}]}.
  All values must be JSON primitives.
- Use ```crab-kpi for a single metric with JSON: version must be 1; title and value
  are required; trend may be up, down, or neutral.
Use the object series format for new charts, for example:
"series":[{"field":"revenue","name":"Revenue"}] and "x":{"field":"month"}.
Do not use the legacy string-array series format.
Never put HTML, SVG, JavaScript, event handlers, URLs, or executable code in
visualization blocks. Do not fabricate data; explain when data is insufficient.
Use ordinary Markdown when a visualization is not helpful.

"""
        + MERMAID_GENERATION_INSTRUCTIONS
        + """
"""
    )
    if req.file_context:
        context.metadata["current_doc"] = req.file_context
    if req.workspace_type:
        context.metadata["workspace_type"] = req.workspace_type
    if req.work_mode:
        context.metadata["work_mode"] = req.work_mode

    if req.images or local_images:
        attached_images = []
        if req.images:
            attached_images.extend(_save_image_temp(img)["file_path"] for img in req.images)
        attached_images.extend(block.get("file_path", "") for block in local_images)
        context.metadata["attached_image_paths"] = [path for path in attached_images if path]
        context.system_prompt += (
            "\n\nWhen the user asks to generate or modify an image based on an attached image, "
            "use the image_edit tool. It uses the most recently attached image automatically; "
            "do not use image_generate for reference-image requests."
        )

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

    from crabagent.core.task.tools import register_task_tools

    register_task_tools(context.tool_registry)

    from crabagent.core.meeting.tools import register_meeting_tools

    register_meeting_tools(context.tool_registry)

    from crabagent.core.mail.tools import register_mail_tools

    register_mail_tools(context.tool_registry)

    from crabagent.core.calendar.tools import register_calendar_tools

    register_calendar_tools(context.tool_registry)

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

    context.current_agent = effective_agent
    context.metadata["_current_agent"] = effective_agent

    from crabagent.core.agent.agent_switch import filter_tool_registry
    from crabagent.core.agent.agents import build_agent_switch_msg, get_agent
    from crabagent.core.agent.agents import get_agent as _get_agent
    from crabagent.core.agent.agents import inject_agent_lessons as _inject_lessons

    if effective_agent == "default":
        _default_profile = await _get_agent("__default__")
        if _default_profile:
            tp = _default_profile.get("tool_permissions", {})
            context.tool_permissions = tp if isinstance(tp, dict) else {}
    else:
        agent_def = await get_agent(effective_agent)
        if agent_def:
            tp = agent_def.get("tool_permissions", {})
            context.tool_permissions = tp if isinstance(tp, dict) else {}
            context.tool_registry = filter_tool_registry(
                context.tool_registry, tool_permissions=context.tool_permissions
            )
            if agent_def.get("model"):
                context.model = agent_def["model"]

    # Add history messages first (any persisted agent_switch messages are included
    # in their correct positions via message_to_dict which converts them to user role)
    for msg_record in history_msgs:
        if msg_record.role == "stats":
            continue
        context.messages.append(message_to_dict(msg_record))

    # Restore accumulated token count for compression threshold check
    if conv.tokens:
        context.total_tokens = conv.tokens

    # Add agent_switch message AFTER history, RIGHT BEFORE the user message
    # so the LLM sees the role switch as the most recent context before responding
    if agent_changed:
        if effective_agent == "default":
            default_profile = await get_agent("__default__")
            if default_profile:
                context.messages.append(build_agent_switch_msg(default_profile, locale=locale))
        else:
            agent_def = await get_agent(effective_agent)
            if agent_def:
                context.messages.append(build_agent_switch_msg(agent_def, locale=locale))

        # Inject per-agent lessons (not cached in system prompt)
        try:
            lessons_block = await _inject_lessons(
                "",
                user_id=user.id,
                agent_name=effective_agent,
                task_hint=(req.message or "")[:120],
            )
            if lessons_block.strip():
                context.messages.append(
                    {"role": "experience", "content": lessons_block.strip(), "agent": effective_agent}
                )
        except Exception:
            pass

    persistence = PersistenceListener(conversation_id=conv.id, branch_id=active_branch)
    persistence.sequence = user_msg_seq
    context.event_bus.subscribe(persistence.on_event)
    # Expose to compress.py for inline persistence during compression
    context.metadata["_persistence"] = persistence

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
    # Keep short tool calls visible long enough for the desktop pet to receive
    # and render their specialized animation after SSE debounce.
    _PET_TOOL_MINIMUM_SECONDS = 1.25

    async def _sse_forward(event: AgentEvent):
        nonlocal _fwd_count, _fwd_last_log, _last_stale_cleanup
        _fwd_count += 1
        now = time.time()

        # Keep the monitor summary authoritative across SSE reconnects and UI refreshes.
        active_info = request.app.state.active_agents.get(session_id)
        if active_info:
            if event.type in (EventType.TOOL_CONFIRM_REQUEST, EventType.USER_INPUT_REQUEST):
                active_info["pet_status"] = "waiting"
                active_info["waiting_type"] = "confirm" if event.type == EventType.TOOL_CONFIRM_REQUEST else "input"
                active_info["waiting_since"] = now
                active_info["tool_name"] = event.data.get("tool_name", "")
            elif event.type in (EventType.TOOL_CALL, EventType.SUB_AGENT_TOOL_CALL):
                active_info["pet_status"] = "working"
                active_info["tool_name"] = event.data.get("name", "")
                active_info["pet_tool_active"] = True
                active_info["pet_tool_min_until"] = now + _PET_TOOL_MINIMUM_SECONDS
                active_info["updated_at"] = now
            elif event.type in (EventType.TOOL_RESULT, EventType.SUB_AGENT_TOOL_RESULT):
                active_info["pet_tool_active"] = False
                # A fast result must not immediately replace the tool state.
                if now >= active_info.get("pet_tool_min_until", 0):
                    active_info["pet_status"] = "thinking"
                    active_info["updated_at"] = now
            elif event.type in (EventType.AGENT_START, EventType.ITERATION_START, EventType.THINKING_DELTA):
                tool_visible = active_info.get("pet_status") == "working" and now < active_info.get(
                    "pet_tool_min_until", 0
                )
                if active_info.get("pet_status") != "waiting" and not tool_visible:
                    active_info["pet_status"] = "thinking"
                    active_info["updated_at"] = now
            elif event.type == EventType.AGENT_ERROR:
                context.metadata["_agent_error"] = True
                active_info["has_error"] = True
                request.app.state.agent_attention[session_id] = {
                    "user_id": user.id,
                    "status": "error",
                    "updated_at": now,
                }

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

    # ── image_generate → screenshot events (show generated images inline) ──
    # Listen for MESSAGE_CREATED (tool result) instead of TOOL_RESULT because
    # TOOL_RESULT carries a truncated preview (2k chars) while MESSAGE_CREATED
    # carries the full result (up to 20k chars).  The full result is needed to
    # reliably parse the JSON with image paths.
    async def _on_image_generated(event: AgentEvent):
        if event.type != EventType.MESSAGE_CREATED:
            return
        msg = event.data.get("message", {})
        if msg.get("role") != "tool":
            return
        if msg.get("name") not in {"image_generate", "image_edit"}:
            return
        result = str(msg.get("content", "") or "")
        if not result:
            return
        try:
            import json as _json

            parsed = _json.loads(result)
        except Exception:
            logger.debug("image_generate: failed to parse tool result JSON")
            return
        image_entries = parsed.get("images", []) if isinstance(parsed, dict) else []
        for entry in image_entries:
            path = entry.get("path", "")
            if not path:
                continue
            try:
                with open(path, "rb") as f:
                    b64 = _b64.b64encode(f.read()).decode()
                # Guess mime from extension
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else "png"
                mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif", "avif": "avif"}
                mime = mime_map.get(ext, "png")
                data_url = f"data:image/{mime};base64,{b64}"
            except Exception:
                logger.debug("image_generate: failed to read image file %s", path, exc_info=True)
                continue
            # Emit SCREENSHOT for live SSE display
            await context.event_bus.emit(
                AgentEvent(
                    type=EventType.SCREENSHOT,
                    data={"image": data_url, "tool": msg.get("name", "image_generate")},
                )
            )
            # Also emit MESSAGE_CREATED so screenshot is persisted to DB.
            # Store file path (not base64) to keep DB small; frontend loads
            # the image via /files/image API on session reload.
            await context.event_bus.emit(
                AgentEvent(
                    type=EventType.MESSAGE_CREATED,
                    data={
                        "message": {
                            "role": "screenshot",
                            "content": path,
                            "agent": msg.get("agent", "default"),
                        }
                    },
                )
            )

    context.event_bus.subscribe(_on_image_generated)

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
        from crabagent.core.agent.middlewares.compress_middleware import CompressMiddleware
        from crabagent.core.agent.middlewares.reflect_middleware import ReflectMiddleware
        from crabagent.core.agent.middlewares.title_middleware import TitleMiddleware

        context.middlewares = MiddlewareChain([CompressMiddleware(), ReflectMiddleware(), TitleMiddleware()])
    except Exception:
        logger.debug("Failed to attach middleware chain", exc_info=True)

    @context.tool_registry.register(
        name="ask_question",
        description=(
            "Ask the user a question and get their response. "
            "Use when you need clarification, more information, "
            "or a decision from the user before proceeding."
        ),
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
            context.metadata["_run_error"] = True
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
                # ── Cumulative token consumption (this run) ──
                "total_prompt": context.accumulated_prompt,
                "total_cached": context.accumulated_cached,
                "total_non_cached": context.accumulated_non_cached,
                "total_completion": context.accumulated_completion,
                "total_reasoning": context.accumulated_reasoning,
                "total_consumed": context.accumulated_total_consumed,
                "iterations": context.iteration,
            }

            import json

            try:
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
            except Exception:
                logger.warning("Failed to emit stats event", exc_info=True)

            try:
                await context.event_bus.emit(
                    AgentEvent(
                        type=EventType.AGENT_END,
                        data=stats_data,
                    )
                )
            except Exception:
                logger.warning("Failed to emit AGENT_END event", exc_info=True)

            await persistence.finalize()

            # Compression persistence is now handled inline by compress.py
            # (persist_compression), so no post-run batch persist is needed.

            # ── Persist per-iteration token usage to DB ──
            if context.usage_records:
                try:
                    from crabagent.core.database import token_usage_batch_create

                    records = [
                        {
                            "user_id": user.id,
                            "session_id": session_id,
                            "agent_name": context.current_agent,
                            "model": resolved_model,
                            "provider": resolved_provider,
                            "branch_id": active_branch,
                            **r,
                        }
                        for r in context.usage_records
                    ]
                    await token_usage_batch_create(records)
                except Exception:
                    logger.debug("Failed to write token_usage", exc_info=True)

            _tasks.pop(session_id, None)
            _session_locks.pop(session_id, None)
            try:
                from crabagent.core.goals.scheduler import schedule_goal_continuation
                from crabagent.core.goals.service import (
                    account_goal_usage,
                    automatic_completion_evidence,
                    checkpoint_goal,
                    finalization_checkpoint,
                    get_current_goal,
                    goal_finalization_required,
                    goal_to_dict,
                )

                async with async_session_factory() as goal_db:
                    goal = await get_current_goal(goal_db, session_id)
                    if goal:
                        if goal_finalization_required(context.metadata):
                            final_reply = context.messages[-1].get("content", "")
                            evidence = automatic_completion_evidence(final_reply)
                            if evidence:
                                from crabagent.core.goals.service import update_goal

                                await update_goal(goal_db, goal, status="complete", evidence=evidence)
                            else:
                                summary, next_step = finalization_checkpoint(final_reply)
                                await checkpoint_goal(goal_db, goal, summary, next_step)
                        limited = False if goal.status == "complete" else await account_goal_usage(
                            goal_db, goal, context.accumulated_total_consumed
                        )
                        await goal_db.commit()
                        snapshot = goal_to_dict(goal)
                    else:
                        limited = False
                        snapshot = None

                if snapshot:
                    event_type = EventType.GOAL_STATUS_CHANGED if limited else EventType.GOAL_UPDATED
                    await context.event_bus.emit(AgentEvent(type=event_type, data={"goal": snapshot}))

                # The next turn is a separate prompt task so cancellation, SSE,
                # and normal session locking continue to work as usual.
                # A failed turn must be terminal for automatic continuation. In
                # particular, an authentication failure cannot be fixed by retrying
                # the same prompt and would otherwise repeat the error indefinitely.
                if _should_continue_goal(snapshot, context.metadata):

                    async def _continue_goal() -> None:
                        try:
                            async with async_session_factory() as goal_check_db:
                                current_goal = await get_current_goal(goal_check_db, session_id)
                                if (
                                    not current_goal
                                    or current_goal.status != "active"
                                    or not current_goal.auto_continue
                                ):
                                    return
                                latest_snapshot = goal_to_dict(current_goal)
                            follow_up = _goal_continuation_request(req)
                            await context.event_bus.emit(
                                AgentEvent(type=EventType.GOAL_CONTINUATION_STARTED, data={"goal": latest_snapshot})
                            )
                            async with async_session_factory() as continue_db:
                                await prompt_async(session_id, follow_up, request, user, continue_db)
                        except Exception:
                            logger.exception("Failed to start goal continuation for session %s", session_id)

                    if schedule_goal_continuation(session_id, _continue_goal):
                        await context.event_bus.emit(
                            AgentEvent(
                                type=EventType.GOAL_CONTINUATION_SCHEDULED, data={"goal": snapshot, "delay_seconds": 2}
                            )
                        )
            except Exception:
                logger.exception("Failed to update goal usage for session %s", session_id)
            request.app.state.active_agents.pop(session_id, None)
            if not context.metadata.get("_run_error") and not context.metadata.get("_agent_error"):
                request.app.state.agent_attention[session_id] = {
                    "user_id": user.id,
                    "status": "completed",
                    "updated_at": time.time(),
                }

            try:
                async with async_session_factory() as update_db:
                    await conv_svc.update_conversation(
                        update_db,
                        session_id,
                        model=resolved_model,
                        provider=resolved_provider,
                        tokens=context.total_tokens,
                    )
            except Exception:
                logger.exception("Failed to update conversation")

    task = asyncio.create_task(_run())
    _tasks[session_id] = task

    request.app.state.active_agents[session_id] = {
        "user_id": user.id,
        "model": req.model or conv.model or "",
        "status": "running",
        # The summary endpoint reads pet_status. Set it immediately so the pet
        # never remains idle while the first model/tool event is pending.
        "pet_status": "working",
        "updated_at": time.time(),
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
    try:
        from crabagent.core.goals.scheduler import cancel_goal_continuation

        cancel_goal_continuation(session_id)
    except Exception:
        pass
    try:
        from crabagent.core.goals.service import get_current_goal, update_goal

        goal = await get_current_goal(db, session_id)
        if goal:
            await update_goal(db, goal, status="paused", stop_reason="Paused by user")
            await db.commit()
    except Exception:
        logger.warning("Failed to pause goal after abort for session %s", session_id, exc_info=True)
    return {"status": "aborted", "session_id": session_id}
