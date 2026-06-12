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
            "[WeChatLoop] Message from %s (%s): %.80s",
            msg.from_user, msg.chat_type, msg.content,
        )

        # Send typing indicator
        await self.client.send_typing(msg.from_user, status=1)

        try:
            reply_text = await _run_agent_for_wechat(msg)
        except Exception as e:
            logger.error("[WeChatLoop] Agent execution failed: %s", e)
            reply_text = f"抱歉，处理消息时出错：{str(e)[:100]}"

        # Send response
        if reply_text:
            await self.client.send_message(
                to_user=msg.from_user,
                text=reply_text,
                context_token=msg.context_token,
            )

        # Stop typing
        await self.client.send_typing(msg.from_user, status=2)

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

async def _run_agent_for_wechat(msg: IncomingMessage) -> str:
    """Run the Agent loop for a WeChat message and return the reply text.

    Reuses an existing WeChat conversation for the same user (multi-turn
    context), or creates a new one on first contact.  The working directory
    is read from :class:`WeChatConfig`.
    """
    import secrets
    from pathlib import Path

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.loop import run_agent
    from crabagent.core.agent.tools.registry import registry
    from crabagent.core.config import settings as app_settings
    from crabagent.core.database import (
        AppSetting,
        Conversation,
        Message as DBMessage,
        async_session_factory,
    )
    from sqlalchemy import select

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
        f"你正在回复微信消息。发送者: {sender_label}。"
        f"请简洁回复，适合手机阅读。工作目录: {workspace}"
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

    # Save user message to DB explicitly (like prompt.py does)
    # run_agent only fires MESSAGE_CREATED for assistant/tool, not user
    try:
        from crabagent.serve.services.message import save_message
        from crabagent.core.database import async_session_factory

        async with async_session_factory() as db:
            await save_message(
                db,
                conversation_id=conv_id,
                sequence=persistence.sequence + 1,
                role="user",
                content=msg.content,
                branch_id="main",
            )
    except Exception as e:
        logger.warning("[WeChatLoop] Failed to save user message: %s", e)

    # Run agent
    app_settings.auto_approve_tools = True
    try:
        await run_agent(context, msg.content)
    except Exception as e:
        logger.error("[WeChatLoop] run_agent error: %s", e)
        return f"处理时出错：{str(e)[:100]}"
    finally:
        app_settings.auto_approve_tools = False
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
    from crabagent.core.molt.tools import register_molt_tools
    from crabagent.core.todo.tools import register_todo_tools
    from crabagent.core.task.tools import register_task_tools
    from crabagent.core.meeting.tools import register_meeting_tools
    from crabagent.core.mail.tools import register_mail_tools
    from crabagent.core.tool_loader import discover_and_register_tools
    from crabagent.core.config import settings as app_settings

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

    from crabagent.core.database import Conversation, Message as DBMessage, async_session_factory
    from sqlalchemy import select

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
