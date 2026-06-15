"""WeChat message loop and Agent bridge.

Runs an async long-poll loop that receives messages from iLink,
forwards them to the CrabAgent Agent loop for processing, and
sends the response back via iLink.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from crabagent.core.wechat.client import IncomingMessage, SessionExpiredError, WeChatClient

logger = logging.getLogger(__name__)

# Backoff on error
_ERROR_BACKOFF = 5.0
# Session expired re-login notification cooldown
_RELOGIN_NOTIFY_COOLDOWN = 300.0  # 5 min


class WeChatMessageLoop:
    """Async long-poll loop that bridges WeChat messages to the Agent.

    Usage::

        loop = WeChatMessageLoop(client, on_message=handle)
        await loop.start()
        # ... later
        await loop.stop()
    """

    def __init__(
        self,
        client: WeChatClient,
        on_message: Any | None = None,
    ):
        self.client = client
        self._custom_handler = on_message
        self._buf = ""
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_relogin_notify = 0.0

    async def start(self) -> None:
        """Start the long-poll loop in a background task."""
        if self._running:
            return
        # Restore persisted context_token into memory cache
        try:
            from crabagent.core.wechat.config import load_config

            cfg = await load_config()
            if cfg.notify_target_user and cfg.cached_context_token:
                self.client._context_store[cfg.notify_target_user] = cfg.cached_context_token
                logger.info(
                    "[WeChatLoop] Restored context_token for %s",
                    cfg.notify_target_user,
                )
        except Exception as e:
            logger.warning("[WeChatLoop] Failed to restore context_token: %s", e)
        self._running = True
        self._task = asyncio.create_task(self._run(), name="wechat-message-loop")
        logger.info("[WeChatLoop] Started")

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[WeChatLoop] Stopped")

    async def _run(self) -> None:
        """Main long-poll loop with error recovery."""
        while self._running:
            try:
                messages = await self.client.get_updates(self._buf)
                for msg in messages:
                    # Update cursor
                    if msg.get_updates_buf:
                        self._buf = msg.get_updates_buf
                    # Persist push target on first incoming message
                    if msg.from_user and msg.context_token:
                        await self._update_push_target(msg.from_user, msg.context_token)
                    # Dispatch
                    asyncio.create_task(self._dispatch(msg))
            except SessionExpiredError:
                logger.warning("[WeChatLoop] Session expired — stopping loop")
                await self._notify_session_expired()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[WeChatLoop] Poll error: %s", e)
                await asyncio.sleep(_ERROR_BACKOFF)

        self._running = False

    async def _update_push_target(self, user_id: str, context_token: str) -> None:
        """Persist the first (or latest) user as the push notification target."""
        try:
            from crabagent.core.wechat.config import load_config, save_config

            cfg = await load_config()
            # Always update context_token; set target_user only if not yet set
            updated = False
            if context_token != cfg.cached_context_token:
                cfg.cached_context_token = context_token
                updated = True
            if not cfg.notify_target_user:
                cfg.notify_target_user = user_id
                logger.info("[WeChatLoop] Push target set to %s", user_id)
                updated = True
            if updated:
                await save_config(cfg)
        except Exception as e:
            logger.warning("[WeChatLoop] Failed to update push target: %s", e)

    async def _dispatch(self, msg: IncomingMessage) -> None:
        """Handle a single incoming message.

        Calls the custom handler if set, otherwise uses the default
        Agent bridge.
        """
        try:
            if self._custom_handler:
                await self._custom_handler(msg)
            else:
                await self._default_handler(msg)
        except Exception as e:
            logger.error("[WeChatLoop] Message dispatch error: %s", e)

    async def _default_handler(self, msg: IncomingMessage) -> None:
        """Default handler: forward to Agent and reply with the response.

        This creates a temporary conversation, runs the Agent, extracts
        the last assistant text, and sends it back via iLink.
        """
        logger.info(
            "[WeChatLoop] Message from %s (%s): %.80s [attachments: %d]",
            msg.from_user, msg.chat_type, msg.content, len(msg.attachments),
        )

        # Send typing indicator
        await self.client.send_typing(msg.from_user, status=1)

        try:
            reply_text = await _run_agent_for_wechat(msg, self.client)
        except Exception as e:
            logger.error("[WeChatLoop] Agent execution failed: %s", e)
            reply_text = f"抱歉，处理消息时出错：{str(e)[:100]}"

        # Send text reply (protected — session may have expired during long tasks)
        reply_sent = False
        if reply_text:
            try:
                reply_sent = await self.client.send_message(
                    to_user=msg.from_user,
                    text=reply_text,
                    context_token=msg.context_token,
                )
            except SessionExpiredError:
                logger.warning("[WeChatLoop] Session expired before final reply could be sent")
            except Exception as e:
                logger.warning("[WeChatLoop] Final reply send failed: %s", e)

        # If reply couldn't be delivered, save it as a notification so the
        # user can see it in the web UI instead of losing it silently.
        if not reply_sent and reply_text:
            logger.warning("[WeChatLoop] Reply not delivered via WeChat, saving as notification")
            try:
                from crabagent.core.database import Notification, async_session_factory

                async with async_session_factory() as db:
                    notif = Notification(
                        user_id=1,
                        title="💬 微信回复发送失败",
                        body=(
                            f"发送给 {msg.from_nickname or msg.from_user} 的回复"
                            "未能送达（会话可能已过期）：\n\n"
                            f"{reply_text[:500]}"
                        ),
                        conversation_id="",
                    )
                    db.add(notif)
                    await db.commit()
            except Exception as e:
                logger.error("[WeChatLoop] Failed to save undelivered reply notification: %s", e)

        # Detect and send files/images referenced in the reply
        try:
            await self._send_reply_attachments(msg, reply_text)
        except SessionExpiredError:
            logger.warning("[WeChatLoop] Session expired before attachments could be sent")
        except Exception as e:
            logger.warning("[WeChatLoop] Send attachments failed: %s", e)

        # Stop typing
        await self.client.send_typing(msg.from_user, status=2)

    async def _send_reply_attachments(self, msg: IncomingMessage, reply_text: str) -> None:
        """Detect image/file references in the reply and send them via WeChat."""
        import re
        from pathlib import Path

        from crabagent.core.wechat.config import load_config

        try:
            cfg = await load_config()
            workspace = Path(cfg.workspace).resolve() if cfg.workspace else Path.cwd().resolve()
        except Exception:
            workspace = Path.cwd().resolve()

        sent: set[str] = set()
        token = msg.context_token

        logger.info("[WeChatLoop] Scanning reply for file refs (%d chars)...", len(reply_text))

        # 1) Markdown images: ![alt](path)
        for m in re.finditer(r'!\[.*?\]\(([^)]+)\)', reply_text):
            img_str = m.group(1).split('?')[0]  # strip query params
            img_path = Path(img_str)
            if not img_path.is_absolute():
                img_path = workspace / img_str
            if img_path.exists() and str(img_path) not in sent:
                if img_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    try:
                        await self.client.send_image(msg.from_user, img_path, token)
                        sent.add(str(img_path))
                    except Exception as e:
                        logger.warning("[WeChatLoop] send_image failed for %s: %s", img_path, e)

        # Common file extensions we can send via WeChat
        _file_exts = (
            r'pdf|xlsx|xls|docx|doc|pptx|ppt|csv|txt|zip|json|md|'
            r'py|js|ts|html|css|sql|rar|7z|tar|gz|epub|mp3|mp4'
        )

        # 2) File references in backticks: `file.xlsx` or `/abs/path/file.pptx`
        for m in re.finditer(
            rf'[`"]([^`"`]+\.(?:{_file_exts}))[`"]', reply_text, re.IGNORECASE
        ):
            fname = m.group(1)
            p = Path(fname)
            if p.is_absolute():
                candidates = [p]
            else:
                candidates = [workspace / fname, workspace / "wechat_files" / fname]
            for candidate in candidates:
                if candidate.exists() and str(candidate) not in sent:
                    try:
                        await self.client.send_file(msg.from_user, candidate, token)
                        sent.add(str(candidate))
                    except Exception as e:
                        logger.warning("[WeChatLoop] send_file failed for %s: %s", candidate, e)
                    break

        # 3) Absolute paths mentioned in the reply (even without backticks)
        for m in re.finditer(
            rf'(/[^\s`"`\'\)]+\.(?:{_file_exts}))', reply_text, re.IGNORECASE
        ):
            p = Path(m.group(1))
            if p.exists() and str(p) not in sent:
                try:
                    if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                        await self.client.send_image(msg.from_user, p, token)
                    else:
                        await self.client.send_file(msg.from_user, p, token)
                    sent.add(str(p))
                except Exception as e:
                    logger.warning("[WeChatLoop] auto-send failed for %s: %s", p, e)

        if sent:
            logger.info("[WeChatLoop] Sent %d attachment(s) via WeChat: %s", len(sent), sent)
        else:
            logger.debug("[WeChatLoop] No file refs found in reply")

    async def _notify_session_expired(self) -> None:
        """Create a notification that WeChat session needs re-login."""
        now = time.time()
        if now - self._last_relogin_notify < _RELOGIN_NOTIFY_COOLDOWN:
            return
        self._last_relogin_notify = now

        try:
            from crabagent.core.database import Notification, async_session_factory

            async with async_session_factory() as db:
                notif = Notification(
                    user_id=1,  # Default admin user
                    title="🔔 微信登录已过期",
                    body="您的微信 iLink Bot 会话已过期，请重新扫码登录。",
                    conversation_id="",
                )
                db.add(notif)
                await db.commit()
        except Exception as e:
            logger.error("[WeChatLoop] Failed to create re-login notification: %s", e)


# ---------------------------------------------------------------------------
# Agent bridge: WeChat message → Agent → reply text
# ---------------------------------------------------------------------------

# ── WeChatProgressListener ──────────────────────────────────────────────────

# Tools that are too lightweight to count toward visible progress
_QUIET_TOOLS = frozenset({
    "read", "glob", "grep", "todo_add", "todo_list", "todo_done",
    "task_list", "task_add", "shared_list", "shared_get",
})

# Fallback: push a heartbeat if no TEXT_DONE for this many seconds
_FALLBACK_INTERVAL = 45.0


class WeChatProgressListener:
    """Push Agent progress updates to WeChat using the Agent's own words.

    Strategy:
      - TEXT_DONE events are buffered in ``_pending``.
      - When a TOOL_CALL fires (meaning another iteration will follow),
        flush ``_pending`` as a WeChat message.
      - The final TEXT_DONE (no subsequent TOOL_CALL) is left buffered —
        ``_default_handler`` sends it as the final reply.
      - A background heartbeat task runs independently: if no push has
        happened for ``_FALLBACK_INTERVAL`` seconds (even during a long
        blocking tool call), it pushes a heartbeat automatically.
    """

    def __init__(
        self,
        client: WeChatClient,
        to_user: str,
    ) -> None:
        self._client = client
        self._to_user = to_user
        self._pending: str = ""
        self._last_push: float = time.monotonic()
        self._tool_count: int = 0
        self._start: float = time.monotonic()
        self._finished: bool = False  # Set by stop() to terminate heartbeat
        self._heartbeat_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background heartbeat task."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="wechat-progress-heartbeat"
            )

    async def stop(self) -> None:
        """Signal the heartbeat loop to stop and wait for cleanup."""
        self._finished = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        """Background loop that pushes heartbeats during long silences.

        Checks every 10 seconds. If no push has occurred for
        ``_FALLBACK_INTERVAL`` seconds, sends a heartbeat.
        This ensures the user still gets feedback even when a single
        tool call blocks for minutes.
        """
        while not self._finished:
            await asyncio.sleep(10)
            if self._finished:
                break
            now = time.monotonic()
            if now - self._last_push >= _FALLBACK_INTERVAL:
                elapsed = int(now - self._start)
                await self._push(
                    f"⏳ 仍在处理中（已完成 {self._tool_count} 步，{elapsed}s）"
                )

    async def on_event(self, event: Any) -> None:
        """EventBus callback — inspects event type and pushes when needed."""
        from crabagent.core.event import AgentEvent, EventType

        if not isinstance(event, AgentEvent):
            return

        if event.type == EventType.TEXT_DONE:
            text = (event.data.get("text") or "").strip()
            if text:
                self._pending = text
            return

        if event.type == EventType.TOOL_CALL:
            name = event.data.get("name", "")
            if name not in _QUIET_TOOLS:
                self._tool_count += 1

            # Agent produced text before this tool call → flush it
            if self._pending:
                await self._push(self._pending)
                self._pending = ""
                return

    async def _push(self, text: str) -> bool:
        """Send a progress message via WeChat.

        Never gives up — the background heartbeat loop will retry
        every ``_FALLBACK_INTERVAL`` seconds on failure.
        Only updates ``_last_push`` on success, so the heartbeat loop
        naturally takes over when sends start failing.

        Does **not** pass a fixed ``context_token`` — delegates to
        :meth:`WeChatClient.send_message` which reads the freshest token
        from ``_context_store``.
        """
        try:
            ok = await self._client.send_message(
                to_user=self._to_user,
                text=text,
            )
            if ok:
                self._last_push = time.monotonic()
                return True
            logger.info("[WeChatProgress] send_message returned False (will retry)")
        except Exception:
            logger.debug("[WeChatProgress] push exception (will retry)", exc_info=True)
        return False


# ── _run_agent_for_wechat ───────────────────────────────────────────────────

async def _run_agent_for_wechat(msg: IncomingMessage, client: WeChatClient | None = None) -> str:
    """Run the Agent loop for a WeChat message and return the reply text.

    Reuses an existing WeChat conversation for the same user (multi-turn
    context), or creates a new one on first contact.  The working directory
    is read from :class:`WeChatConfig`.
    """
    from pathlib import Path

    from sqlalchemy import select

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.loop import run_agent
    from crabagent.core.agent.tools.registry import registry
    from crabagent.core.config import settings as app_settings
    from crabagent.core.database import (
        AppSetting,
        async_session_factory,
    )

    # ---- Resolve workspace from config ----
    from crabagent.core.wechat.config import load_config

    cfg = await load_config()
    workspace = Path(cfg.workspace).resolve() if cfg.workspace else Path.cwd().resolve()

    # ---- Resolve model ----
    default_model = app_settings.default_model
    try:
        async with async_session_factory() as sdb:
            r = await sdb.execute(select(AppSetting).where(AppSetting.key == "default_model"))
            row = r.scalar_one_or_none()
            if row and row.value:
                default_model = row.value
    except Exception:
        pass

    sender_label = msg.from_nickname or msg.from_user
    title = f"微信 - {sender_label}"
    system_prompt = (
        f"你正在回复微信消息。发送者: {sender_label}。\n"
        f"请简洁回复，适合手机阅读。工作目录: {workspace}\n\n"
        f"## 微信文件能力\n"
        f"你**可以**向微信用户发送文件和图片。当用户需要文件时：\n"
        f"- 用工具（如 write、office_create 等）将文件写到工作目录\n"
        f"- 在回复文本中用 markdown 格式引用文件路径，系统会自动检测并发送\n"
        f"  - 图片：`![描述](路径)` → 自动作为微信图片发送\n"
        f"  - 文件：在回复中提及完整文件路径（如 `/path/to/report.pdf`），或用反引号包裹文件名\n"
        f"- 支持的文件类型：图片(png/jpg/gif/webp)、文档(pdf/xlsx/docx/pptx/csv/txt/zip/json/md等所有常见格式)\n"
        f"- 发送后用户在微信中会收到文件，无需额外操作\n"
        f"- 如果用户要的内容适合直接发送文件，**优先发文件**而不是把内容贴在聊天里\n"
    )

    # ---- Find or create conversation (reuse per user) ----
    session_id, conv_id, existing_messages = await _find_or_create_wechat_conversation(
        from_user=msg.from_user,
        title=title,
        workspace=str(workspace),
        model=default_model,
    )

    context = AgentContext(
        workspace=workspace,
        tool_registry=registry,
        max_iterations=app_settings.max_iterations,
        model=default_model or None,
        system_prompt=system_prompt,
    )

    # Hydrate prior messages for multi-turn context
    # Only include user and assistant roles to avoid broken tool_call chains
    for m in existing_messages:
        role = m["role"]
        if role in ("user", "assistant"):
            context.messages.append({"role": role, "content": m["content"]})

    # Register tools
    await _register_tools(context, workspace)

    context.metadata["session_id"] = session_id
    context.metadata["branch_id"] = "main"
    context.metadata["_db_conversation_id"] = conv_id

    # Subscribe persistence listener
    from crabagent.serve.services.persistence import PersistenceListener

    persistence = PersistenceListener(conversation_id=conv_id, branch_id="main")
    context.event_bus.subscribe(persistence.on_event)

    # Subscribe WeChat progress listener for real-time status updates
    progress = None
    if client:
        progress = WeChatProgressListener(
            client=client,
            to_user=msg.from_user,
        )
        context.event_bus.subscribe(progress.on_event)
        progress.start()  # Launch background heartbeat timer

    # Save user message to DB explicitly (like prompt.py does)
    # run_agent only fires MESSAGE_CREATED for assistant/tool, not user
    display_content = msg.content
    if msg.attachments:
        att_parts = []
        for a in msg.attachments:
            if a.media_type == "voice" and a.asr_text:
                att_parts.append(f"[语音] {a.asr_text}")
            elif a.media_type == "image":
                att_parts.append(f"[图片 {a.width}x{a.height}]")
            elif a.media_type == "file":
                att_parts.append(f"[文件: {a.file_name}]")
            elif a.media_type == "video":
                att_parts.append(f"[视频 {a.duration}s]")
            else:
                att_parts.append(f"[{a.media_type}]")
        display_content = f"{msg.content} {' '.join(att_parts)}".strip()

    try:
        from crabagent.core.database import async_session_factory
        from crabagent.serve.services.message import save_message

        async with async_session_factory() as db:
            await save_message(
                db,
                conversation_id=conv_id,
                sequence=persistence.sequence + 1,
                role="user",
                content=display_content,
                branch_id="main",
            )
    except Exception as e:
        logger.warning("[WeChatLoop] Failed to save user message: %s", e)

    # ---- Process attachments into query content ----
    query: str | list[dict] = msg.content
    if msg.attachments:
        import base64 as _b64

        content_blocks: list[dict] = []

        for att in msg.attachments:
            if att.media_type == "image":
                if client:
                    try:
                        raw_bytes = await client.download_media(att)
                        if raw_bytes and len(raw_bytes) < 5_000_000:  # 5MB limit
                            b64 = _b64.b64encode(raw_bytes).decode("ascii")
                            data_url = f"data:image/jpeg;base64,{b64}"
                            content_blocks.append({
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            })
                            content_blocks.append({
                                "type": "text",
                                "text": f"[用户发送了一张图片，{att.width}x{att.height}]",
                            })
                        else:
                            content_blocks.append({
                                "type": "text",
                                "text": f"[用户发送了一张图片，但下载失败或过大（{len(raw_bytes)} bytes）]",
                            })
                    except Exception as e:
                        logger.warning("[WeChatLoop] Image download failed: %s", e)
                        content_blocks.append({
                            "type": "text",
                            "text": f"[用户发送了一张图片，但处理失败：{e}]",
                        })
                else:
                    content_blocks.append({
                        "type": "text",
                        "text": f"[用户发送了一张图片，{att.width}x{att.height}]",
                    })

            elif att.media_type == "voice":
                asr = att.asr_text or "(无法识别的语音消息)"
                content_blocks.append({
                    "type": "text",
                    "text": f"[用户发送了语音消息] {asr}",
                })

            elif att.media_type == "file":
                if client:
                    try:
                        raw_bytes = await client.download_media(att)
                        if raw_bytes:
                            save_dir = workspace / "wechat_files"
                            save_dir.mkdir(parents=True, exist_ok=True)
                            file_path = save_dir / (att.file_name or f"file_{att.file_size}")
                            file_path.write_bytes(raw_bytes)
                            content_blocks.append({
                                "type": "text",
                                "text": f"[用户发送了文件「{att.file_name}」，已保存到 {file_path}]",
                            })
                        else:
                            content_blocks.append({
                                "type": "text",
                                "text": f"[用户发送了文件「{att.file_name}」，但下载失败]",
                            })
                    except Exception as e:
                        logger.warning("[WeChatLoop] File download failed: %s", e)
                        content_blocks.append({
                            "type": "text",
                            "text": f"[用户发送了文件「{att.file_name}」，但处理失败：{e}]",
                        })
                else:
                    content_blocks.append({
                        "type": "text",
                        "text": f"[用户发送了文件「{att.file_name}」]",
                    })

            elif att.media_type == "video":
                content_blocks.append({
                    "type": "text",
                    "text": f"[用户发送了一段视频，时长 {att.duration}s，暂不支持视频处理]",
                })

        # Append original text if present
        if msg.content:
            content_blocks.append({"type": "text", "text": msg.content})

        query = content_blocks if content_blocks else msg.content

    # Run agent
    app_settings.auto_approve_tools = True
    try:
        await run_agent(context, query)
    except Exception as e:
        logger.error("[WeChatLoop] run_agent error: %s", e)
        return f"处理时出错：{str(e)[:100]}"
    finally:
        app_settings.auto_approve_tools = False
        # Stop the heartbeat timer
        if progress:
            await progress.stop()
        # Cleanup
        browser_mgr = context.metadata.get("_browser_manager")
        if browser_mgr:
            try:
                await browser_mgr.close()
            except Exception:
                pass
        mcp_mgr = context.metadata.get("_mcp_manager")
        if mcp_mgr:
            try:
                import asyncio as _a
                await _a.wait_for(mcp_mgr.stop_all(), timeout=10)
            except Exception:
                pass

    # Extract last assistant text
    reply = _extract_last_assistant_text(context)
    return reply or "（无回复内容）"


async def _register_tools(context, workspace) -> None:
    """Register all available tools to the AgentContext."""
    from crabagent.core.agent.skill.loader import discover_skills, register_skill_tool
    from crabagent.core.config import settings as app_settings
    from crabagent.core.mail.tools import register_mail_tools
    from crabagent.core.meeting.tools import register_meeting_tools
    from crabagent.core.molt.tools import register_molt_tools
    from crabagent.core.task.tools import register_task_tools
    from crabagent.core.todo.tools import register_todo_tools
    from crabagent.core.tool_loader import discover_and_register_tools

    skill_dirs = app_settings.skill_discovery_dirs()
    skills = discover_skills(skill_dirs)
    if skills:
        register_skill_tool(context.tool_registry, skills)

    register_molt_tools(context.tool_registry)
    register_todo_tools(context.tool_registry)
    register_task_tools(context.tool_registry)
    register_meeting_tools(context.tool_registry)
    register_mail_tools(context.tool_registry)
    discover_and_register_tools(context.tool_registry, workspace)

    # MCP tools
    try:
        from crabagent.core.mcp.client import MCPClientManager
        from crabagent.core.mcp.tools import register_mcp_tools

        mcp_manager = MCPClientManager()
        await mcp_manager.start_all()
        register_mcp_tools(context.tool_registry, mcp_manager)
        context.metadata["_mcp_manager"] = mcp_manager
    except Exception:
        pass


async def _find_or_create_wechat_conversation(
    from_user: str,
    title: str,
    workspace: str,
    model: str,
) -> tuple[str, int, list[dict]]:
    """Find an existing WeChat conversation for *from_user* or create a new one.

    Returns ``(session_id, conversation_id, prior_messages)`` where
    *prior_messages* is a list of ``{"role": …, "content": …}`` dicts
    for multi-turn context.
    """
    import secrets

    from sqlalchemy import select

    from crabagent.core.database import Conversation, async_session_factory
    from crabagent.core.database import Message as DBMessage

    async with async_session_factory() as db:
        # Try to find an existing wechat conversation for this user
        stmt = (
            select(Conversation)
            .where(
                Conversation.source == "wechat",
                Conversation.user_id == 1,
                Conversation.title == title,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()

        if conv:
            # Load recent messages for context
            msg_result = await db.execute(
                select(DBMessage)
                .where(
                    DBMessage.conversation_id == conv.id,
                    DBMessage.branch_id == "main",
                )
                .order_by(DBMessage.id.desc())
                .limit(20)
            )
            msgs = list(reversed(msg_result.scalars().all()))
            prior = [
                {"role": m.role, "content": m.content}
                for m in msgs
                if m.content and m.role in ("user", "assistant")
            ]
            # Touch updated_at
            conv.updated_at = conv.updated_at  # trigger onupdate
            await db.commit()
            logger.info(
                "[WeChatLoop] Reusing conversation: session=%s, %d prior msgs",
                conv.session_id, len(prior),
            )
            return conv.session_id, conv.id, prior

        # Create new conversation
        session_id = secrets.token_hex(16)
        conv = Conversation(
            session_id=session_id,
            user_id=1,
            title=title[:500],
            workspace=workspace,
            model=model,
            source="wechat",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        logger.info("[WeChatLoop] New conversation created: session=%s", session_id)
        return session_id, conv.id, []


def _extract_last_assistant_text(context) -> str:
    """Extract the last assistant text message from the context.

    Messages are plain dicts with ``role`` and ``content`` keys.
    """
    for msg in reversed(context.messages):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant" and msg.get("content", "").strip():
                return msg["content"].strip()
        elif hasattr(msg, "role"):
            if msg.role == "assistant" and getattr(msg, "content", "").strip():
                return msg.content.strip()
    return ""
