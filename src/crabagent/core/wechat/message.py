"""WeChat message loop and Agent bridge.

Runs an async long-poll loop that receives messages from iLink,
forwards them to the CrabAgent Agent loop for processing, and
sends the response back via iLink.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from crabagent.core.wechat.client import IncomingMessage, SessionExpiredError, WeChatClient
from crabagent.core.wechat.process_lock import acquire_process_lock

logger = logging.getLogger(__name__)

# Backoff on error
_ERROR_BACKOFF = 5.0
# Give up and rebuild the whole loop after this many consecutive poll errors.
# (Each failed cycle ≈ _LONG_POLL_TIMEOUT 45s + _ERROR_BACKOFF 5s, so 5 errors
# ≈ 4 minutes of dead connection before self-healing kicks in.)
_MAX_CONSECUTIVE_POLL_ERRORS = 5
# Self-heal notification cooldown
_SELFHEAL_NOTIFY_COOLDOWN = 600.0  # 10 min
# Session expired re-login notification cooldown
_RELOGIN_NOTIFY_COOLDOWN = 300.0  # 5 min
# Archive a WeChat conversation when prior messages exceed this count
_WECHAT_ARCHIVE_MSG_THRESHOLD = 150
# Hydration safety: cap a single history message's content length (chars).
# Messages carrying base64 data-URLs (saved tool/vision outputs) can be
# megabytes each and blow past the model's prompt limit.
_WECHAT_HYDRATE_MAX_CHARS = 20_000
# Marker substituted for stripped base64 data URLs
_WECHAT_BASE64_PLACEHOLDER = "[图片数据已省略，如需查看请让用户重新发送或使用图片工具]"


_WECHAT_COMMANDS = ("/状态", "/模型", "/工作空间", "/会话", "/新会话", "/帮助")

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
        on_connection_lost: Any | None = None,
    ):
        self.client = client
        self._custom_handler = on_message
        # Async callback fired (as a background task) when the poll loop
        # gives up after too many consecutive errors. The owner (scheduler)
        # uses it to rebuild the loop with a fresh HTTP client.
        self._on_connection_lost = on_connection_lost
        self._buf = ""
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_relogin_notify = 0.0
        self._last_selfheal_notify = 0.0
        # Message deduplication: msg_key → timestamp (monotonic)
        # Prevents the same message from being processed twice if
        # long-poll returns it in consecutive batches.
        self._recent_msgs: dict[str, float] = {}
        self._dedup_ttl = 120.0  # seconds
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._active_runs: dict[str, dict] = {}
        self._dispatch_tails: dict[str, asyncio.Task] = {}
        self._dispatch_tasks: set[asyncio.Task] = set()
        self._lock_file = None

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
        from crabagent.core.database import engine

        url = engine.url
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            raise RuntimeError("WeChat polling requires a file-backed SQLite database")
        lock_file = acquire_process_lock(os.path.realpath(url.database) + ".wechat.lock")
        self._lock_file = lock_file
        self._running = True
        self._task = asyncio.create_task(self._run_locked(), name="wechat-message-loop")
        logger.info("[WeChatLoop] Started")

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        was_running = self._running
        self._running = False
        if self._task:
            # Let the wrapper enter its finally block even on immediate stop.
            await asyncio.sleep(0)
            if not self._task.done() and was_running:
                self._task.cancel()
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
        logger.info("[WeChatLoop] Stopped")

    async def _run_locked(self) -> None:
        try:
            await self._run()
        finally:
            self._running = False
            while self._dispatch_tasks or self._active_runs:
                tasks = set(self._dispatch_tasks) | {v["task"] for v in self._active_runs.values() if "task" in v}
                if not tasks:
                    break
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(0)
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None

    def _track_dispatch(self, task: asyncio.Task) -> None:
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    async def _run(self) -> None:
        """Main long-poll loop with error recovery."""
        consecutive_errors = 0
        while self._running:
            try:
                messages = await self.client.get_updates(self._buf)
                consecutive_errors = 0
                for msg in messages:
                    # Update cursor
                    if msg.get_updates_buf:
                        self._buf = msg.get_updates_buf
                    # Reset per-user send counter for the new message round
                    if msg.from_user:
                        self.client.reset_send_count(msg.from_user)
                    # Dispatch
                    self._schedule_dispatch(msg)
            except SessionExpiredError:
                logger.warning("[WeChatLoop] Session expired — stopping loop")
                await self._notify_session_expired()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    "[WeChatLoop] Poll error (%d/%d): %s",
                    consecutive_errors,
                    _MAX_CONSECUTIVE_POLL_ERRORS,
                    e,
                )
                if consecutive_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                    logger.warning(
                        "[WeChatLoop] %d consecutive poll errors — connection degraded,"
                        " giving up this loop and requesting a rebuild",
                        consecutive_errors,
                    )
                    self._running = False
                    await self._notify_connection_degraded()
                    # Fire the rebuild callback in its own task — it will call
                    # loop.stop() which awaits this very task, so we must not
                    # await it inline (deadlock).
                    if self._on_connection_lost:
                        asyncio.create_task(self._safe_connection_lost())
                    break
                await asyncio.sleep(_ERROR_BACKOFF)

        self._running = False

    async def _safe_connection_lost(self) -> None:
        """Invoke the connection-lost callback, swallowing exceptions."""
        try:
            await self._on_connection_lost()
        except Exception as e:
            logger.error("[WeChatLoop] Connection-lost callback failed: %s", e)

    async def _notify_connection_degraded(self) -> None:
        """Create an in-app notification that the WeChat loop is self-healing."""
        now = time.time()
        if now - self._last_selfheal_notify < _SELFHEAL_NOTIFY_COOLDOWN:
            return
        self._last_selfheal_notify = now

        try:
            from crabagent.core.database import Notification, async_session_factory

            async with async_session_factory() as db:
                notif = Notification(
                    user_id=1,  # Default admin user
                    title="🔄 微信通道自愈",
                    body=(
                        "微信 iLink 连接连续失败，已自动重建消息循环。"
                        "如持续提示无法连接，请尝试重启应用或重新扫码登录。"
                    ),
                    conversation_id="",
                )
                db.add(notif)
                await db.commit()
        except Exception as e:
            logger.error("[WeChatLoop] Failed to create self-heal notification: %s", e)

    async def _update_push_target(self, user_id: str, context_token: str) -> None:
        """Persist the first (or latest) user as the push notification target."""
        try:
            from crabagent.core.wechat.config import load_config, save_config

            cfg = await load_config()
            updated = False
            if not cfg.notify_target_user:
                cfg.notify_target_user = user_id
                logger.info("[WeChatLoop] Push target set to %s", user_id)
                updated = True
            if cfg.notify_target_user == user_id and context_token != cfg.cached_context_token:
                cfg.cached_context_token = context_token
                updated = True
            if updated:
                await save_config(cfg)
        except Exception as e:
            logger.warning("[WeChatLoop] Failed to update push target: %s", e)

    def _is_duplicate(self, msg: IncomingMessage) -> bool:
        """Check if a message was already processed recently.

        Uses a composite key of from_user + content + msg_id (if available)
        with a time-based TTL to handle long-poll re-delivery.
        """
        now = time.monotonic()

        # Purge expired entries
        expired = [k for k, ts in self._recent_msgs.items() if now - ts > self._dedup_ttl]
        for k in expired:
            del self._recent_msgs[k]

        # Build dedup key — prefer msg_id, fall back to content hash
        if msg.msg_id:
            key = f"{msg.from_user}:{msg.msg_id}"
        else:
            # Fall back: user + content (trimmed)
            content_key = msg.content[:200] if msg.content else ""
            key = f"{msg.from_user}:{hash(content_key)}"

        if key in self._recent_msgs:
            logger.warning("[WeChatLoop] Duplicate message detected, skipping: %s", key[:60])
            return True

        self._recent_msgs[key] = now
        return False

    @staticmethod
    def _is_switch_command(msg: IncomingMessage) -> bool:
        parts = (msg.content or "").strip().split(maxsplit=1)
        if not parts:
            return False
        command = parts[0]
        argument = parts[1].strip() if len(parts) > 1 else ""
        return bool(command == "/新会话" or
                    (command in {"/工作空间", "/会话"} and argument) or
                    (command == "/模型" and len(argument.split(maxsplit=1)) == 2))

    async def _prepare_deferred_switch(self, msg: IncomingMessage, queued: bool) -> bool:
        from crabagent.core.wechat.config import load_config

        cfg = await load_config()
        if (not cfg.enabled or not cfg.auto_reply or not msg.from_user
                or (cfg.allowed_users and msg.from_user not in cfg.allowed_users) or self._is_duplicate(msg)):
            return False
        if msg.context_token:
            await self._update_push_target(msg.from_user, msg.context_token)
        if queued:
            try:
                await self.client.send_message(
                    to_user=msg.from_user,
                    text="切换命令已排队，将在当前任务结束后按顺序执行；重启后未执行的队列会丢失。",
                )
            except Exception:
                logger.warning("[WeChatLoop] Failed to acknowledge queued switch", exc_info=True)
        return True

    def _schedule_dispatch(self, msg: IncomingMessage) -> None:
        """Preserve arrival order per sender without blocking other senders."""
        sender = msg.from_user
        previous = self._dispatch_tails.get(sender)
        command = (msg.content or "").strip().split(maxsplit=1)[:1]
        active = self._active_runs.get(sender)
        if not self._custom_handler and self._is_switch_command(msg):
            queued = bool((active and not active["task"].done()) or (previous and not previous.done()))
            preparation = asyncio.create_task(self._prepare_deferred_switch(msg, queued))
            self._track_dispatch(preparation)

            async def apply_switch():
                accepted = await preparation
                if previous:
                    try:
                        await asyncio.shield(previous)
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        logger.warning("[WeChatLoop] Previous dispatch was cancelled")
                    except Exception:
                        logger.exception("[WeChatLoop] Previous dispatch failed")
                if not accepted:
                    return
                active_run = self._active_runs.get(sender)
                if active_run and not active_run["task"].done():
                    try:
                        await asyncio.shield(active_run["task"])
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        logger.warning("[WeChatLoop] Active run was cancelled before queued switch")
                    except Exception:
                        logger.exception("[WeChatLoop] Active run failed before queued switch")
                await self._dispatch(msg, prechecked=True)

            task = asyncio.create_task(apply_switch())
            self._track_dispatch(task)
            self._dispatch_tails[sender] = task
            def cleanup_switch(done):
                if self._dispatch_tails.get(sender) is done:
                    self._dispatch_tails.pop(sender, None)
            task.add_done_callback(cleanup_switch)
            return
        # Read-only commands may bypass an occupied sender queue.
        read_only = {"/状态", "/模型", "/工作空间", "/会话", "/帮助"}
        if command and command[0] in read_only and active and not active["task"].done():
            task = asyncio.create_task(self._dispatch(msg))
            self._track_dispatch(task)
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            return

        async def dispatch_ordered():
            if previous:
                try:
                    await asyncio.shield(previous)
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    logger.warning("[WeChatLoop] Previous dispatch was cancelled")
                except Exception:
                    logger.exception("[WeChatLoop] Previous dispatch failed")
            await self._dispatch(msg)

        task = asyncio.create_task(dispatch_ordered())
        self._track_dispatch(task)
        self._dispatch_tails[sender] = task
        def cleanup(done):
            if self._dispatch_tails.get(sender) is done:
                self._dispatch_tails.pop(sender, None)
        task.add_done_callback(cleanup)

    async def _dispatch(self, msg: IncomingMessage, *, prechecked: bool = False) -> None:
        """Handle a single incoming message.

        Calls the custom handler if set, otherwise uses the default
        Agent bridge.
        """
        from crabagent.core.wechat.config import load_config

        cfg = await load_config()
        if (not cfg.enabled or not cfg.auto_reply or not msg.from_user
                or (cfg.allowed_users and msg.from_user not in cfg.allowed_users)):
            logger.info("[WeChatLoop] Ignoring unauthorized or disabled message")
            return
        if not prechecked:
            if self._is_duplicate(msg):
                return
            if msg.context_token:
                await self._update_push_target(msg.from_user, msg.context_token)

        try:
            head = (msg.content or "").strip().split(maxsplit=1)[:1]
            if not self._custom_handler and head in [[c] for c in _WECHAT_COMMANDS]:
                lock = self._user_locks.setdefault(msg.from_user, asyncio.Lock())
                active = self._active_runs.get(msg.from_user)
                if lock.locked() and active and not active["task"].done():
                    parts = (msg.content or "").strip().split(maxsplit=1)
                    command = parts[0]
                    argument = parts[1].strip() if len(parts) > 1 else ""
                    switching = (command == "/新会话" or
                                 (command in {"/工作空间", "/会话"} and argument) or
                                 (command == "/模型" and len(argument.split(maxsplit=1)) == 2))
                    if switching:
                        await self.client.send_message(
                            to_user=msg.from_user,
                            text="当前有运行中的任务，请等待完成后再切换。",
                        )
                    else:
                        await self._handle_command(msg)
                else:
                    async with lock:
                        await self._handle_command(msg)
                return
            if self._custom_handler:
                await self._custom_handler(msg)
                return
            lock = self._user_locks.setdefault(msg.from_user, asyncio.Lock())
            async with lock:
                active = self._active_runs.get(msg.from_user)
                if active and not active["task"].done():
                    ready = asyncio.create_task(active["ready"].wait())
                    await asyncio.wait({ready, active["task"]}, return_when=asyncio.FIRST_COMPLETED)
                    if not ready.done():
                        ready.cancel()
                    context = active.get("context")
                    if context and context.metadata.get("_accept_followups") and not context.budget_exhausted:
                        query = await _wechat_query(msg, self.client, context.workspace)
                        if context.metadata.get("_accept_followups") and not context.budget_exhausted:
                            context.metadata.setdefault("_pending_user_messages", []).append(query)
                            return
                    await active["task"]
                active = {"ready": asyncio.Event(), "context": None}
                self._active_runs[msg.from_user] = active
                task = asyncio.create_task(self._default_handler(msg, active))
                active["task"] = task
                def finished(done):
                    if self._active_runs.get(msg.from_user) is active:
                        self._active_runs.pop(msg.from_user, None)
                    if not done.cancelled() and done.exception():
                        logger.error("[WeChatLoop] Handler failed: %s", done.exception())
                task.add_done_callback(finished)
        
        except Exception as e:
            logger.error("[WeChatLoop] Message dispatch error: %s", e)

    async def _handle_command(self, msg: IncomingMessage) -> bool:
        """Keep channel commands out of the agent and active follow-up queue."""
        parts = (msg.content or "").strip().split(maxsplit=1)
        if not parts or parts[0] not in {"/状态", "/模型", "/工作空间", "/会话", "/新会话", "/帮助"}:
            return False
        from pathlib import Path

        from crabagent.core.provider_store import list_providers
        from crabagent.core.wechat.config import load_config
        from crabagent.core.wechat.selection import available_workspaces, conversations, load, save, workspace_path
        from crabagent.serve.api.provider import get_provider_models

        command = parts[0]
        argument = parts[1].strip() if len(parts) > 1 else ""
        cfg = await load_config()
        title = _wechat_identity_title(cfg.account_id, msg.from_user)
        state = await load(cfg.account_id, msg.from_user)
        workspace = state.get("workspace") or workspace_path(cfg.workspace or str(Path.cwd()))
        active = self._active_runs.get(msg.from_user)
        running = bool(active and not active["task"].done())
        if command == "/帮助":
            reply = (
                "微信命令：/状态、/模型 [服务商 模型]、/工作空间 [路径]、/会话 [编号]、/新会话。"
                "运行中切换会排队，任务结束后生效；重启会丢失未执行的队列。"
            )
        elif command == "/状态":
            provider_label = state.get("provider", "默认")
            model_label = state.get("model", "默认")
            session_label = state.get("sessions", {}).get(workspace, "自动")
            reply = (
                f"当前运行：{'处理中' if running else '空闲'}\n"
                f"工作空间：{workspace}\n"
                f"模型：{provider_label} / {model_label}\n"
                f"会话：{session_label}"
            )
            context = active.get("context") if running else None
            if context:
                current_provider = getattr(context, "provider_name", None) or "默认"
                reply += (
                    f"\n本次运行工作空间：{context.workspace}"
                    f"\n本次运行模型：{context.model or '默认'}"
                    f"\n本次运行服务商：{current_provider}"
                )
        elif running and (
            command == "/新会话"
            or (command in {"/工作空间", "/会话"} and argument)
            or (command == "/模型" and len(argument.split(maxsplit=1)) == 2)
        ):
            reply = "当前有运行中的任务，请等待完成后再切换。"
        elif command == "/模型":
            providers = [p for p in await list_providers() if p.enabled]
            if not argument:
                names = "、".join(p.name for p in providers) or "无"
                reply = f"可用服务商：{names}\n使用 /模型 服务商 模型；或 /模型 服务商 查看模型。"
            else:
                values = argument.split(maxsplit=1)
                provider = next((p for p in providers if p.name == values[0]), None)
                if not provider:
                    reply = "服务商不存在或未启用，配置未更改。"
                else:
                    try:
                        models = [item["id"] for item in await get_provider_models(provider.name, user=None)]
                    except Exception:
                        logger.warning("[WeChatLoop] Failed to list provider models", exc_info=True)
                        models = []
                    if len(values) == 1:
                        reply = "可用模型：" + ("、".join(models) if models else "无法获取模型列表，配置未更改。")
                    elif values[1] not in models:
                        reply = "模型不在该服务商可用列表中或列表获取失败，配置未更改。"
                    else:
                        state.update(provider=provider.name, model=values[1])
                        await save(cfg.account_id, msg.from_user, state)
                        reply = f"已选择模型：{provider.name} / {values[1]}"
        elif command == "/工作空间":
            available = await available_workspaces(cfg)
            if not argument:
                reply = "可用工作空间：\n" + "\n".join(available)
            else:
                try:
                    chosen = workspace_path(argument)
                except (OSError, RuntimeError, ValueError):
                    chosen = ""
                if chosen not in available:
                    reply = "工作空间不在可用列表中或目录不存在，配置未更改。"
                else:
                    state["workspace"] = chosen
                    await save(cfg.account_id, msg.from_user, state)
                    reply = f"已切换工作空间：{chosen}"
        elif command == "/会话":
            items = await conversations(title, workspace)
            if not argument:
                listing = "\n".join(f"{c.id}: {c.session_id}" for c in items[:30]) or "无"
                reply = f"当前工作空间的会话：\n{listing}\n使用 /会话 编号切换。"
            else:
                chosen = next((c for c in items if str(c.id) == argument or c.session_id == argument), None)
                if not chosen:
                    reply = "会话不存在或不属于当前用户及工作空间。"
                else:
                    state.setdefault("sessions", {})[workspace] = chosen.id
                    await save(cfg.account_id, msg.from_user, state)
                    reply = f"已切换会话：{chosen.id}"
        else:
            state.setdefault("sessions", {})[workspace] = 0
            await save(cfg.account_id, msg.from_user, state)
            reply = "已选择新会话，下条消息将创建。"
        await self.client.send_message(to_user=msg.from_user, text=reply)
        return True

    async def _default_handler(self, msg: IncomingMessage, active: dict | None = None) -> None:
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
            reply_text, _ = await _run_agent_for_wechat(msg, self.client, active)
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
            workspace_hint = active.get("context").workspace if active and active.get("context") else None
            await self._send_reply_attachments(msg, reply_text, workspace_hint)
        except SessionExpiredError:
            logger.warning("[WeChatLoop] Session expired before attachments could be sent")
        except Exception as e:
            logger.warning("[WeChatLoop] Send attachments failed: %s", e)

        # Stop typing
        await self.client.send_typing(msg.from_user, status=2)

    async def _send_reply_attachments(self, msg: IncomingMessage, reply_text: str, run_workspace=None) -> None:
        """Detect image/file references in the reply and send them via WeChat."""
        import re
        from pathlib import Path

        from crabagent.core.wechat.config import load_config

        try:
            cfg = await load_config()
            workspace = Path(run_workspace or cfg.workspace or Path.cwd()).resolve()
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
                # Sync with global count
                self._send_count = self._client.get_send_count(self._to_user)
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

        Increments the **global** per-user send counter on success
        so that the consolidation threshold is enforced across all
        concurrent dispatches to the same user.
        """
        try:
            ok = await self._client.send_message(
                to_user=self._to_user,
                text=text,
            )
            if ok:
                self._last_push = time.monotonic()
                # Use global counter from client (shared across dispatches)
                self._send_count = self._client.increment_send_count(self._to_user)
                self._typing_warned = False
                return True
            return False
        except Exception:
            logger.debug("[WeChatProgress] send exception", exc_info=True)
            return False

    async def _push(self, text: str) -> bool:
        """Send a progress message, switch to consolidation on overflow.

        After ``_MAX_INDIVIDUAL_SENDS`` (7) individual sends (counted
        globally per-user across all concurrent dispatches):
        - The **8th** push sends a one-time notification to the user
          ("⏳ 任务较长，完成后统一推送") then consolidates.
        - Subsequent pushes are accumulated in ``_consolidated``
          and delivered as a single batch merged with the final reply.
        """
        # Sync local count with global count at entry
        self._send_count = self._client.get_send_count(self._to_user)

        # ── Consolidation mode ──────────────────────────────────────
        if self._send_count >= self._MAX_INDIVIDUAL_SENDS:
            # 8th push: send a one-line notification to set expectations
            if self._send_count == self._MAX_INDIVIDUAL_SENDS:
                self._client.increment_send_count(self._to_user)  # Mark notification as "sent"
                self._send_count += 1
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


def sanitize_history_content(content: str) -> str:
    """Strip base64 data-URLs and oversize content from a history message.

    Some persisted messages (e.g. vision tool outputs) contain entire
    images as base64 data-URLs.  Rehydrating them verbatim makes every
    subsequent LLM call exceed the prompt limit ("Prompt exceeds max
    length", GLM code 1261), which used to silently break the channel.
    """
    if not content:
        return content
    import re as _re

    # Replace data URLs (possibly inside JSON content blocks)
    cleaned = _re.sub(
        r"data:image/[a-zA-Z+]+;base64,[A-Za-z0-9+/=]+",
        _WECHAT_BASE64_PLACEHOLDER,
        content,
    )
    # Hard cap oversized messages
    if len(cleaned) > _WECHAT_HYDRATE_MAX_CHARS:
        cleaned = cleaned[:_WECHAT_HYDRATE_MAX_CHARS] + "\n…[历史消息过长，已截断]"
    return cleaned


def _wechat_identity_title(account_id: str, from_user: str) -> str:
    """Use an opaque stable channel identity, never a mutable display name."""
    import hashlib
    import json

    identity = json.dumps([account_id, from_user], ensure_ascii=True, separators=(",", ":"))
    return "微信 - identity " + hashlib.sha256(identity.encode()).hexdigest()


async def _run_agent_for_wechat(
    msg: IncomingMessage,
    client: WeChatClient | None = None,
    active: dict | None = None,
) -> tuple[str, int]:
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
    from crabagent.core.wechat.selection import available_workspaces, load, save, workspace_path
    state = await load(cfg.account_id, msg.from_user)
    selected_workspace = workspace_path(state.get("workspace") or cfg.workspace or str(Path.cwd()))
    if selected_workspace not in await available_workspaces(cfg):
        raise ValueError("当前工作空间不可用或授权已撤销，请使用 /工作空间 重新选择。")
    workspace = Path(selected_workspace)

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

    provider_name = state.get("provider") or None
    selected_model = state.get("model") or None
    if bool(provider_name) != bool(selected_model):
        raise ValueError("微信模型配置不完整，请重新选择服务商和模型。")
    if not selected_model:
        from crabagent.core.agent.loop import _get_default_model_settings, _resolve_provider
        saved_model, saved_provider = await _get_default_model_settings()
        selected_model = saved_model or app_settings.default_model
        provider_name = (await _resolve_provider(saved_provider)).name
    sender_label = msg.from_nickname or msg.from_user
    # Legacy nickname-based conversations cannot be attributed safely.
    title = _wechat_identity_title(cfg.account_id, msg.from_user)
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
        selected_id=state.get("sessions", {}).get(str(workspace)),
    )
    state.setdefault("sessions", {})[str(workspace)] = conv_id
    await save(cfg.account_id, msg.from_user, state)

    # Compact in place before hydration: the selected conversation ID remains stable.
    from crabagent.core.wechat.compaction import compact
    if await compact(cfg.account_id, msg.from_user, str(workspace), conv_id, title,
                     selected_model or default_model, provider_name,
                     threshold=_WECHAT_ARCHIVE_MSG_THRESHOLD):
        session_id, conv_id, existing_messages = await _find_or_create_wechat_conversation(
            msg.from_user, title, str(workspace), default_model, selected_id=conv_id)

    context = AgentContext(
        workspace=workspace,
        tool_registry=registry.clone(),
        max_iterations=app_settings.max_iterations,
        model=selected_model,
        provider_name=provider_name,
        system_prompt=system_prompt,
    )

    # Hydrate prior messages for multi-turn context
    # Only include user and assistant roles to avoid broken tool_call chains
    for m in existing_messages:
        role = m["role"]
        if role in ("user", "assistant", "compress"):
            context.messages.append(
                {"role": role, "content": sanitize_history_content(m["content"])}
            )

    # Register tools
    await _register_tools(context, workspace)

    context.metadata["session_id"] = session_id
    context.metadata["branch_id"] = "main"
    context.metadata["_db_conversation_id"] = conv_id

    # Subscribe persistence listener
    from crabagent.serve.services.persistence import PersistenceListener

    persistence = PersistenceListener(conversation_id=conv_id, branch_id="main")
    context.event_bus.subscribe(persistence.on_event)

    from crabagent.core.database import Conversation
    from crabagent.serve.services.usage import UsagePersistenceListener

    async with async_session_factory() as db:
        from sqlalchemy import func

        from crabagent.core.database import Message as DBMessage

        conversation = await db.get(Conversation, conv_id)
        usage_user_id = conversation.user_id
        persistence.sequence = await db.scalar(
            select(func.max(DBMessage.sequence)).where(
                DBMessage.conversation_id == conv_id,
                DBMessage.branch_id == "main",
            )
        ) or 0
    usage = UsagePersistenceListener(context, usage_user_id, session_id)
    context.event_bus.subscribe(usage.on_event)

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
            persistence.sequence += 1
            await save_message(
                db,
                conversation_id=conv_id,
                sequence=persistence.sequence,
                role="user",
                content=display_content,
                branch_id="main",
            )
    except Exception as e:
        logger.warning("[WeChatLoop] Failed to save user message: %s", e)

    query = await _wechat_query(msg, client, workspace)

    # Run agent — no need to mutate the global auto_approve_tools flag.
    # This context has no confirm_callback, so tools auto-execute.
    # Mutating the global was unsafe: a concurrent desktop prompt would read
    # True and skip installing its own confirm_callback.
    # Snapshot the message count so reply extraction only considers messages
    # produced by *this* run — otherwise a failed run would replay the last
    # assistant message from the hydrated history as if it were a fresh reply.
    _run_start_msg_count = len(context.messages)
    context.metadata["_accept_followups"] = True
    if active is not None:
        active["context"] = context
        active["ready"].set()
    try:
        await run_agent(context, query)
    except Exception as e:
        logger.error("[WeChatLoop] run_agent error: %s", e)
        return f"处理时出错：{str(e)[:100]}", conv_id
    finally:
        context.metadata["_accept_followups"] = False
        from crabagent.core.agent.loop import _consume_user_messages
        await _consume_user_messages(context)
        await usage.flush()
        await persistence.finalize()
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

    # Extract last assistant text — only from THIS run's messages, never
    # from the hydrated history (a failed run must not replay old replies).
    # (If run_agent raised, we already returned an error message above.)
    reply = _extract_last_assistant_text(context, start_index=_run_start_msg_count)

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


async def _wechat_query(msg, client, workspace):
    """Build the same multimodal query for initial and follow-up messages."""
    from pathlib import Path
    # ---- Voice-only: promote ASR text to message content ----
    if not msg.content and msg.attachments:
        for att in msg.attachments:
            if att.media_type == "voice" and att.asr_text:
                msg.content = att.asr_text
                break

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
                            img_filename = f"wechat_img_{_time.time_ns()}.jpg"
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
                # If ASR was already promoted to msg.content, skip the wrapper
                if not (msg.content == asr):
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
                            fallback = f"file_{att.file_size}"
                            file_path = save_dir / (Path(att.file_name).name if att.file_name else fallback)
                            file_path.write_bytes(raw_bytes)
                            # Auto-extract content for readable file types
                            file_content = await _extract_file_content(file_path, att.file_name or "")
                            if file_content:
                                content_blocks.append(
                                    {
                                        "type": "text",
                                        "text": (
                                            f"[用户发送了文件「{att.file_name}」，已保存到 {file_path}]\n\n"
                                            f"文件内容如下：\n{file_content}"
                                        ),
                                    }
                                )
                            else:
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

    return query


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
    selected_id: int | None = None,
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
                Conversation.workspace == workspace,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        if selected_id is not None:
            stmt = stmt.where(Conversation.id == selected_id)
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if selected_id and not conv:
            raise ValueError("Selected WeChat session is unavailable")

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
                    DBMessage.compressed == False,  # noqa: E712
                )
                .order_by(DBMessage.sequence, DBMessage.id)
            )
            msgs = list(msg_result.scalars().all())
            prior = [
                {"role": m.role, "content": m.content}
                for m in msgs
                if m.content and m.role in ("user", "assistant", "compress")
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


async def _summarize_conversation(messages: list[dict], model: str, provider_name: str | None = None) -> str:
    """One-shot LLM summarization of conversation history.

    Reuses the i18n compress prompt for consistency with the main
    agent's context compression flow.
    """
    import litellm

    from crabagent.core.agent.loop import _get_default_model_settings, _litellm_params, _resolve_provider
    from crabagent.core.proxy import resolve_llm_proxy

    # Keep this formatter local: the generic compression module exposes no
    # private formatting helper, which broke rollover in packaged builds.
    history_text = "\n\n".join(
        f"### {message.get('role', 'user')}\n{message.get('content', '')}"
        for message in messages
        if message.get("content")
    )
    system_prompt = "你是一个对话摘要生成器。"
    user_prompt = (
        "请全面、详细地总结以下对话历史。必须保留所有关键事实、决策、文件路径、"
        "代码变更细节以及继续对话所需的任何重要上下文。用中文撰写。使用 Markdown "
        "格式组织内容（标题、列表、代码块等）。不要省略任何重要细节——宁可详细也"
        "不能遗漏。**输出不超过 5000 字**，在保证完整性的前提下尽量精简。\n\n"
        f"需要总结的对话：\n{history_text}"
    )

    _, default_provider = await _get_default_model_settings()
    provider = await _resolve_provider(provider_name or default_provider)
    llm_params = _litellm_params(provider, await resolve_llm_proxy(provider))
    if "/" not in model:
        model = f"{'chatgpt' if provider.provider_type == 'chatgpt' else 'openai'}/{model}"

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


async def _maybe_archive_after_reply(conv_id: int, title: str) -> bool:
    """Archive a stale WeChat conversation and report whether it rolled over.

    Called before a new turn is hydrated so the first message of a new day uses
    the previous day's summary instead of the full archived history.

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
        async_session_factory,
    )
    from crabagent.core.database import (
        Message as DBMessage,
    )
    from crabagent.serve.services.message import save_message

    try:
        async with async_session_factory() as db:
            conv = await db.get(Conversation, conv_id)
            if not conv:
                return False

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
                return False

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
            prior = [
                {"role": m.role, "content": sanitize_history_content(m.content or "")}
                for m in msgs
            ]

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
                    return False
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
            return True

    except Exception as e:
        logger.error("[WeChatLoop] Archive task failed: %s", e)
        return False


async def _extract_file_content(file_path, original_name: str) -> str | None:
    """Try to read readable file content; return content string or None.

    Handles plain text files (txt, md, csv, json, yaml, code, config, etc.)
    and Office documents (xlsx, docx, pptx) via OfficeCLI.
    """
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    text_exts = {
        "txt", "md", "csv", "json", "yaml", "yml", "toml", "xml",
        "py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "c", "cpp",
        "sh", "bash", "sql", "css", "scss", "html", "vue", "svelte",
        "ini", "cfg", "conf", "env", "log", "gradle", "kt", "swift",
    }
    if ext in text_exts:
        try:
            content = file_path.read_text("utf-8")
            if len(content) > 8000:
                content = content[:8000] + "\n\n... (文件过长，已截断)"
            return content
        except Exception:
            return None
    if ext in ("xlsx", "docx", "pptx"):
        try:
            from crabagent.core.office.manager import get_office_manager
            mgr = get_office_manager()
            if mgr.available:
                result = await mgr.view_text(str(file_path), mode="text", max_lines=200)
                if result.success and result.data:
                    text = result.data[:8000]
                    return text
        except Exception:
            pass
    return None


def _extract_last_assistant_text(context, start_index: int = 0) -> str:
    """Extract the last assistant text message from the context.

    Messages are plain dicts with ``role`` and ``content`` keys.
    ``start_index`` limits the scan to messages produced at or after that
    position — pass the pre-run message count so a failed run cannot
    replay an old assistant message from the hydrated history.
    """
    for msg in reversed(context.messages[start_index:]):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant" and msg.get("content", "").strip():
                return msg["content"].strip()
        elif hasattr(msg, "role"):
            if msg.role == "assistant" and getattr(msg, "content", "").strip():
                return msg.content.strip()
    return ""
