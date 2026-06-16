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
# Archive a WeChat conversation when prior messages exceed this count
_WECHAT_ARCHIVE_MSG_THRESHOLD = 150


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
            msg.from_user,
            msg.chat_type,
            msg.content,
            len(msg.attachments),
        )

        # Send typing indicator
        await self.client.send_typing(msg.from_user, status=1)

        try:
            reply_text, conv_id = await _run_agent_for_wechat(msg, self.client)
        except Exception as e:
            logger.error("[WeChatLoop] Agent execution failed: %s", e)
            reply_text = f"抱歉，处理消息时出错：{str(e)[:100]}"
            conv_id = 0

        # Send text reply (protected — session may have expired during long tasks)
        reply_sent = False
        if reply_text:
            try:
                reply_sent = await self.client.send_message(
                    to_user=msg.from_user,
                    text=reply_text,
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

        # Async post-reply archive check — zero user-perceived latency
        if conv_id:
            sender_label = msg.from_nickname or msg.from_user
            asyncio.create_task(
                _maybe_archive_after_reply(
                    conv_id=conv_id,
                    title=f"微信 - {sender_label} v2",
                )
            )

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
        token = self.client._context_store.get(msg.from_user, "")

        logger.info("[WeChatLoop] Scanning reply for file refs (%d chars)...", len(reply_text))

        # 1) Markdown images: ![alt](path)
        for m in re.finditer(r"!\[.*?\]\(([^)]+)\)", reply_text):
            img_str = m.group(1).split("?")[0]  # strip query params
            img_path = Path(img_str)
            if not img_path.is_absolute():
                img_path = workspace / img_str
            if img_path.exists() and str(img_path) not in sent:
                if img_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    try:
                        await self.client.send_image(msg.from_user, img_path, token)
                        sent.add(str(img_path))
                    except Exception as e:
                        logger.warning("[WeChatLoop] send_image failed for %s: %s", img_path, e)

        # Common file extensions we can send via WeChat
        _file_exts = (
            r"pdf|xlsx|xls|docx|doc|pptx|ppt|csv|txt|zip|json|md|"
            r"py|js|ts|html|css|sql|rar|7z|tar|gz|epub|mp3|mp4"
        )

        # 2) File references in backticks: `file.xlsx` or `/abs/path/file.pptx`
        for m in re.finditer(rf'[`"]([^`"`]+\.(?:{_file_exts}))[`"]', reply_text, re.IGNORECASE):
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
        for m in re.finditer(rf'(/[^\s`"`\'\)]+\.(?:{_file_exts}))', reply_text, re.IGNORECASE):
            p = Path(m.group(1))
            if p.exists() and str(p) not in sent:
                try:
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
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
_QUIET_TOOLS = frozenset(
    {
        "read",
        "glob",
        "grep",
        "todo_add",
        "todo_list",
        "todo_done",
        "task_list",
        "task_add",
        "shared_list",
        "shared_get",
    }
)

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
      - A background heartbeat task runs independently with three jobs:
        1. **Typing keepalive** — sends ``send_typing(status=1)`` every
           ~5s during long tasks.
        2. **Heartbeat text** — if no push has happened for
           ``_FALLBACK_INTERVAL`` seconds, pushes a status message.
        3. **Buffer flush** — when sends fail, messages are buffered and
           retried with exponential backoff.

      - **Consolidation mode**: iLink silently drops sends after roughly
        10 consecutive pushes. After ``_MAX_INDIVIDUAL_SENDS`` (8)
        individual pushes, all further progress is accumulated and
        delivered as a single batch merged with the final reply.
    """

    # Send typing indicator this often (protocol recommends every 5s)
    _TYPING_INTERVAL = 5.0
    # Max buffered messages before merging old ones
    _MAX_BUFFER = 20
    # iLink drops sends after ~10; consolidate after this many
    _MAX_INDIVIDUAL_SENDS = 7

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

        # --- Resilient delivery ---
        self._buffer: list[str] = []  # Messages waiting for retry
        self._backoff: float = 5.0  # Current retry backoff (seconds)
        self._max_backoff: float = 120.0
        self._last_retry: float = 0.0  # Time of last buffer-flush attempt
        self._last_typing: float = 0.0  # Time of last typing keepalive
        self._typing_warned: bool = False  # Suppress repeated logging

        # --- Consolidation (iLink ~10-send limit) ---
        self._send_count: int = 0  # How many individual sends succeeded
        self._consolidated: list[str] = []  # Messages for final batch delivery

    def start(self) -> None:
        """Start the background heartbeat task."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="wechat-progress-heartbeat")

    async def stop(self) -> None:
        """Signal the heartbeat loop to stop and wait for cleanup.

        Makes a final attempt to flush any buffered messages.
        """
        self._finished = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        # Final attempt to flush buffered messages
        if self._buffer:
            merged = "\n---\n".join(self._buffer)
            try:
                ok = await self._client.send_message(self._to_user, merged)
                if ok:
                    logger.info(
                        "[WeChatProgress] Final flush: sent %d buffered messages",
                        len(self._buffer),
                    )
                    self._buffer.clear()
            except Exception:
                logger.warning(
                    "[WeChatProgress] Final flush failed, %d messages lost",
                    len(self._buffer),
                )

    async def _heartbeat_loop(self) -> None:
        """Background loop: typing keepalive + heartbeat + buffer flush.

        Runs every 10 seconds. Each iteration:
        1. Sends typing indicator to keep context_token alive.
        2. If there are buffered messages and backoff has elapsed, tries
           to flush them.
        3. If no heartbeat text has been pushed for a while (and we're
           not in degraded mode), pushes a status message.
        """
        while not self._finished:
            await asyncio.sleep(10)
            if self._finished:
                break
            now = time.monotonic()

            # 1. Typing keepalive — prevents context_token expiry
            if now - self._last_typing >= self._TYPING_INTERVAL:
                self._last_typing = now
                try:
                    await self._client.send_typing(self._to_user, status=1)
                    self._typing_warned = False
                except Exception:
                    if not self._typing_warned:
                        logger.debug("[WeChatProgress] typing keepalive failed (token may be stale)")
                        self._typing_warned = True

            # 2. Flush buffered messages with exponential backoff
            if self._buffer and (now - self._last_retry) >= self._backoff:
                self._last_retry = now
                merged = "\n---\n".join(self._buffer)
                ok = await self._send(merged)
                if ok:
                    logger.info(
                        "[WeChatProgress] Recovered! Flushed %d buffered messages",
                        len(self._buffer),
                    )
                    self._buffer.clear()
                    self._backoff = 5.0  # Reset backoff on recovery

            # 3. Normal heartbeat — skip when degraded or in
            # consolidation mode to avoid filling the batch with noise.
            if not self._buffer and now - self._last_push >= _FALLBACK_INTERVAL:
                if self._send_count >= self._MAX_INDIVIDUAL_SENDS:
                    # In consolidation mode: user already received the
                    # "完成后统一推送" notification; heartbeat would only
                    # bloat the final merged message.
                    continue
                elapsed = int(now - self._start)
                await self._push(f"⏳ 仍在处理中（已完成 {self._tool_count} 步，{elapsed}s）")

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

    async def _send(self, text: str) -> bool:
        """Low-level send — calls client.send_message, returns success.

        Increments ``_send_count`` on success so the consolidation
        threshold in ``_push`` stays accurate.
        """
        try:
            ok = await self._client.send_message(
                to_user=self._to_user,
                text=text,
            )
            if ok:
                self._last_push = time.monotonic()
                self._send_count += 1
                self._typing_warned = False
                return True
            return False
        except Exception:
            logger.debug("[WeChatProgress] send exception", exc_info=True)
            return False

    async def _push(self, text: str) -> bool:
        """Send a progress message, switch to consolidation on overflow.

        After ``_MAX_INDIVIDUAL_SENDS`` (7) individual sends:
        - The **8th** push sends a one-time notification to the user
          ("⏳ 任务较长，完成后统一推送") then consolidates.
        - Subsequent pushes are accumulated in ``_consolidated``
          and delivered as a single batch merged with the final reply.
        """
        # ── Consolidation mode ──────────────────────────────────────
        if self._send_count >= self._MAX_INDIVIDUAL_SENDS:
            # 8th push: send a one-line notification to set expectations
            if self._send_count == self._MAX_INDIVIDUAL_SENDS:
                self._send_count += 1  # Mark notification as "sent"
                await self._client.send_message(
                    self._to_user,
                    "⏳ 任务较长，完成后统一推送后续进度和结果",
                )
            # Accumulate real progress for final batch
            self._consolidated.append(text)
            logger.info("[WeChatProgress] consolidation mode: queued (%d)", len(self._consolidated))
            return True

        ok = await self._send(text)
        if ok:
            return True

        # First failure: give the long-poll a moment to pick up any
        # new message with a fresh context_token, then retry once.
        await asyncio.sleep(2)
        ok = await self._send(text)
        if ok:
            return True

        # Still failed: buffer for retry — keep at most _MAX_BUFFER entries
        if len(self._buffer) >= self._MAX_BUFFER:
            # Merge oldest two to make room
            self._buffer[0] = self._buffer[0] + "\n" + self._buffer[1]
            del self._buffer[1]
        self._buffer.append(text)

        # Exponential backoff
        self._backoff = min(self._backoff * 1.5, self._max_backoff)
        logger.info(
            "[WeChatProgress] send failed, buffered message (total=%d, next retry in %.0fs)",
            len(self._buffer),
            self._backoff,
        )
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
    title = f"微信 - {sender_label} v2"
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
        f"- 如果用户要的内容适合直接发送文件，**优先发文件**而不是把内容贴在聊天里\n\n"
        f"## 图片识别能力\n"
        f"当用户发送图片时，图片会保存到本地文件并提供给你。如果你自身无法直接查看图片，\n"
        f"请检查你是否有图片识别/分析相关的工具（如 vision、image analyze 等），有就调用。\n"
        f"如果确实没有任何图片识别手段，再如实告诉用户。\n"
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
                dim = f"{a.width}x{a.height}" if a.width and a.height else ""
                att_parts.append(f"[图片{f' {dim}' if dim else ''}]")
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
                            # Save to local file for vision tool access
                            import time as _time
                            save_dir = workspace / "wechat_files"
                            save_dir.mkdir(parents=True, exist_ok=True)
                            img_filename = f"wechat_img_{int(_time.time())}.jpg"
                            img_path = save_dir / img_filename
                            img_path.write_bytes(raw_bytes)

                            # Provide both base64 (for vision-capable models) and
                            # text instructions (for non-vision models to use vision tools)
                            b64 = _b64.b64encode(raw_bytes).decode("ascii")
                            data_url = f"data:image/jpeg;base64,{b64}"
                            content_blocks.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url},
                                }
                            )
                            content_blocks.append(
                                {
                                    "type": "text",
                                    "text": (
                                        f"[用户发送了一张图片，已保存到 {img_path}]\n"
                                        f"如果你无法直接看到图片内容，请检查你是否有图片识别相关的工具可以分析这张图片。"
                                    ),
                                }
                            )
                        else:
                            content_blocks.append(
                                {
                                    "type": "text",
                                    "text": f"[用户发送了一张图片，但下载失败或过大（{len(raw_bytes)} bytes）]",
                                }
                            )
                    except Exception as e:
                        logger.warning("[WeChatLoop] Image download failed: %s", e)
                        content_blocks.append(
                            {
                                "type": "text",
                                "text": f"[用户发送了一张图片，但处理失败：{e}]",
                            }
                        )
                else:
                    content_blocks.append(
                        {
                            "type": "text",
                            "text": f"[用户发送了一张图片，{att.width}x{att.height}]",
                        }
                    )

            elif att.media_type == "voice":
                asr = att.asr_text or "(无法识别的语音消息)"
                content_blocks.append(
                    {
                        "type": "text",
                        "text": f"[用户发送了语音消息] {asr}",
                    }
                )

            elif att.media_type == "file":
                if client:
                    try:
                        raw_bytes = await client.download_media(att)
                        if raw_bytes:
                            save_dir = workspace / "wechat_files"
                            save_dir.mkdir(parents=True, exist_ok=True)
                            file_path = save_dir / (att.file_name or f"file_{att.file_size}")
                            file_path.write_bytes(raw_bytes)
                            content_blocks.append(
                                {
                                    "type": "text",
                                    "text": f"[用户发送了文件「{att.file_name}」，已保存到 {file_path}]",
                                }
                            )
                        else:
                            content_blocks.append(
                                {
                                    "type": "text",
                                    "text": f"[用户发送了文件「{att.file_name}」，但下载失败]",
                                }
                            )
                    except Exception as e:
                        logger.warning("[WeChatLoop] File download failed: %s", e)
                        content_blocks.append(
                            {
                                "type": "text",
                                "text": f"[用户发送了文件「{att.file_name}」，但处理失败：{e}]",
                            }
                        )
                else:
                    content_blocks.append(
                        {
                            "type": "text",
                            "text": f"[用户发送了文件「{att.file_name}」]",
                        }
                    )

            elif att.media_type == "video":
                content_blocks.append(
                    {
                        "type": "text",
                        "text": f"[用户发送了一段视频，时长 {att.duration}s，暂不支持视频处理]",
                    }
                )

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
        return f"处理时出错：{str(e)[:100]}", conv_id
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

    # If consolidation mode was active, merge buffered progress with
    # the final reply so everything arrives in one iLink send.
    if progress and progress._consolidated:
        parts = list(progress._consolidated)
        if reply:
            parts.append(reply)
        merged = "\n\n".join(parts)
        logger.info(
            "[WeChatProgress] Consolidation: %d msgs + reply merged (%d chars)",
            len(progress._consolidated),
            len(merged),
        )
        return merged, conv_id

    return reply or "（无回复内容）", conv_id


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

    from crabagent.core.calendar.tools import register_calendar_tools

    register_calendar_tools(context.tool_registry)

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
            # Load all messages for context — no limit.
            # DeepSeek V4 supports 1M tokens, so we can safely include
            # the full conversation.  An unrestricted read also maximises
            # prompt caching (the prefix never changes between turns).
            msg_result = await db.execute(
                select(DBMessage)
                .where(
                    DBMessage.conversation_id == conv.id,
                    DBMessage.branch_id == "main",
                )
                .order_by(DBMessage.id)
            )
            msgs = list(msg_result.scalars().all())
            prior = [
                {"role": m.role, "content": m.content} for m in msgs if m.content and m.role in ("user", "assistant")
            ]
            # Touch updated_at
            conv.updated_at = conv.updated_at  # trigger onupdate
            await db.commit()
            logger.info(
                "[WeChatLoop] Reusing conversation: session=%s, %d prior msgs",
                conv.session_id,
                len(prior),
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


# ---------------------------------------------------------------------------
# Conversation archival: periodically roll over a long WeChat conversation
# into a fresh one with an LLM-generated summary, to prevent unbounded
# context growth.  Runs asynchronously after the user has already received
# their reply — zero perceived latency.
# ---------------------------------------------------------------------------


async def _summarize_conversation(messages: list[dict], model: str) -> str:
    """One-shot LLM summarization of conversation history.

    Reuses the i18n compress prompt for consistency with the main
    agent's context compression flow.
    """
    import litellm

    from crabagent.core.agent.compress import _format_messages
    from crabagent.core.provider_store import get_default_provider

    history_text = _format_messages(messages)
    system_prompt = "你是一个对话摘要生成器。"
    user_prompt = (
        "请全面、详细地总结以下对话历史。必须保留所有关键事实、决策、文件路径、"
        "代码变更细节以及继续对话所需的任何重要上下文。用中文撰写。使用 Markdown "
        "格式组织内容（标题、列表、代码块等）。不要省略任何重要细节——宁可详细也"
        "不能遗漏。**输出不超过 5000 字**，在保证完整性的前提下尽量精简。\n\n"
        f"需要总结的对话：\n{history_text}"
    )

    # Resolve provider params (api_key, api_base, custom_llm_provider)
    provider = await get_default_provider()
    if not provider:
        raise RuntimeError("No LLM provider configured")
    llm_params: dict = {"api_key": provider.api_key}
    if provider.base_url:
        llm_params["api_base"] = provider.base_url
        llm_params["custom_llm_provider"] = "openai"

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4096,
        stream=False,
        **llm_params,
    )
    return response.choices[0].message.content.strip()


async def _maybe_archive_after_reply(conv_id: int, title: str) -> None:
    """Check if a WeChat conversation should be archived and create
    a fresh one with a summary.

    Runs asynchronously after the user has already received their reply.

    Triggers:
      1. **Date** — conversation was created on a previous day.
      2. **Volume** — prior messages exceed *_WECHAT_ARCHIVE_MSG_THRESHOLD*.
    """
    import datetime
    import secrets

    from sqlalchemy import func, select

    from crabagent.core.database import (
        AppSetting,
        Conversation,
        Message as DBMessage,
        async_session_factory,
    )
    from crabagent.serve.services.message import save_message

    try:
        async with async_session_factory() as db:
            conv = await db.get(Conversation, conv_id)
            if not conv:
                return

            # --- Condition 1: Date trigger ---
            created_date = conv.created_at.date()
            today = datetime.date.today()
            date_trigger = created_date < today

            # --- Condition 2: Volume trigger ---
            count_result = await db.execute(
                select(func.count(DBMessage.id)).where(
                    DBMessage.conversation_id == conv_id,
                    DBMessage.branch_id == "main",
                    DBMessage.role.in_(["user", "assistant"]),
                    DBMessage.content != "",
                )
            )
            prior_count = count_result.scalar() or 0
            volume_trigger = prior_count > _WECHAT_ARCHIVE_MSG_THRESHOLD

            if not date_trigger and not volume_trigger:
                return

            reason = "跨天归档" if date_trigger else f"消息超限归档({prior_count})"
            logger.info(
                "[WeChatLoop] Archiving conv #%d (%s, %d prior msgs, created %s)",
                conv_id,
                reason,
                prior_count,
                created_date.isoformat(),
            )

            # 1. Load prior messages for summarization
            msg_result = await db.execute(
                select(DBMessage)
                .where(
                    DBMessage.conversation_id == conv_id,
                    DBMessage.branch_id == "main",
                    DBMessage.role.in_(["user", "assistant"]),
                    DBMessage.content != "",
                )
                .order_by(DBMessage.id)
            )
            msgs = list(msg_result.scalars().all())
            prior = [{"role": m.role, "content": m.content} for m in msgs]

            # 2. Summarize (skip if too few messages)
            summary = ""
            if len(prior) >= 4:
                # Resolve model
                model = "deepseek-v4-flash"
                try:
                    r = await db.execute(
                        select(AppSetting).where(AppSetting.key == "default_model")
                    )
                    row = r.scalar_one_or_none()
                    if row and row.value:
                        model = row.value
                except Exception:
                    pass

                try:
                    summary = await _summarize_conversation(prior, model)
                except Exception as e:
                    logger.warning("[WeChatLoop] Summary failed, skipping archive: %s", e)
                    return
            else:
                logger.info("[WeChatLoop] Only %d msgs, skipping summary", len(prior))

            # 3. Archive old conversation — rename title so it won't match lookups
            archive_tag = datetime.datetime.now().strftime("%m-%d %H:%M")
            conv.title = f"{title[:400]} (已归档 {archive_tag})"

            # 4. Create new conversation
            new_session_id = secrets.token_hex(16)
            new_conv = Conversation(
                session_id=new_session_id,
                user_id=conv.user_id,
                title=title,
                workspace=conv.workspace or "",
                model=conv.model or "",
                source="wechat",
            )
            db.add(new_conv)
            await db.commit()
            await db.refresh(new_conv)

            # 5. Inject summary as initial context
            if summary:
                await save_message(
                    db,
                    conversation_id=new_conv.id,
                    sequence=1,
                    role="user",
                    content=f"[以下是之前对话的摘要]\n\n{summary}",
                    branch_id="main",
                )
                await save_message(
                    db,
                    conversation_id=new_conv.id,
                    sequence=2,
                    role="assistant",
                    content="好的，我已了解之前的对话背景，请继续。",
                    branch_id="main",
                )
                await db.commit()

            logger.info(
                "[WeChatLoop] Archive done: conv #%d → #%d, summary=%d chars",
                conv_id,
                new_conv.id,
                len(summary),
            )

    except Exception as e:
        logger.error("[WeChatLoop] Archive task failed: %s", e)


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
