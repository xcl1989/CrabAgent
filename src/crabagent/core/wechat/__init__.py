"""WeChat (iLink Bot) integration for CrabAgent.

Provides:
- WeChatClient — iLink protocol HTTP client
- WeChatMessageLoop — async long-poll → Agent bridge
- WeChatNotification — proactive push notifications to WeChat
- Auth flow — QR code login + credential persistence
"""

from __future__ import annotations

import logging

from crabagent.core.wechat.auth import (
    get_authenticated_client,
    is_logged_in,
    logout,
    start_login,
    wait_for_login,
)
from crabagent.core.wechat.client import (
    IncomingMessage,
    LoginCredentials,
    MediaAttachment,
    QRCodeResult,
    SessionExpiredError,
    WeChatClient,
)
from crabagent.core.wechat.config import WeChatConfig, load_config, save_config
from crabagent.core.wechat.message import WeChatMessageLoop

logger = logging.getLogger(__name__)

__all__ = [
    "WeChatClient",
    "WeChatMessageLoop",
    "WeChatConfig",
    "IncomingMessage",
    "MediaAttachment",
    "LoginCredentials",
    "QRCodeResult",
    "SessionExpiredError",
    "load_config",
    "save_config",
    "start_login",
    "wait_for_login",
    "get_authenticated_client",
    "is_logged_in",
    "logout",
    "WeChatNotification",
]


class WeChatNotification:
    """Push notifications to WeChat via iLink.

    Usage::

        await WeChatNotification.send("任务 #42 已逾期", user_id="wxid_xxx")
    """

    @staticmethod
    async def send(text: str, user_id: str = "") -> bool:
        """Send a notification message to WeChat.

        Args:
            text: Notification text (supports emoji).
            user_id: Target WeChat user ID. If empty, tries to use the
                     last user who sent a message (from context_token cache).

        Returns:
            ``True`` on success, ``False`` if not logged in or send failed.
        """
        # Priority 1: use the running message loop's client (has cached context_tokens)
        client = None
        try:
            from crabagent.serve.scheduler import get_scheduler

            sched = get_scheduler()
            loop = getattr(sched, "_wechat_loop", None)
            if loop and loop._running and loop.client._context_store:
                client = loop.client
        except Exception:
            pass

        # Priority 2: create a fresh client from saved config
        if not client:
            client = await get_authenticated_client()
        if not client:
            logger.debug("[WeChatNotify] Not logged in — skipping")
            return False

        try:
            if not user_id:
                # Try to find any cached user from memory
                if client._context_store:
                    user_id = next(iter(client._context_store))
                else:
                    # Fall back to persisted target user + context_token
                    cfg = await load_config()
                    if cfg.notify_target_user and cfg.cached_context_token:
                        user_id = cfg.notify_target_user
                        # Inject the persisted token into the client's store
                        client._context_store[user_id] = cfg.cached_context_token
                        logger.info(
                            "[WeChatNotify] Using persisted target: %s",
                            user_id,
                        )
                    else:
                        logger.warning(
                            "[WeChatNotify] No target user — send a WeChat message to the bot first"
                        )
                        return False

            success = await client.send_message(to_user=user_id, text=text)
            if not client._http or client._http.is_closed:
                pass  # Already closed by send_message
            else:
                await client.close()
            return success
        except Exception as e:
            logger.error("[WeChatNotify] Failed: %s", e)
            try:
                await client.close()
            except Exception:
                pass
            return False

    @staticmethod
    async def send_task_overdue(task: dict, user_id: str = "") -> bool:
        """Send a task overdue notification."""
        title = task.get("title", "未知任务")
        deadline = task.get("deadline", "未知")
        text = f"⚠️ 任务逾期\n\n📋 {title}\n📅 截止：{deadline}"
        return await WeChatNotification.send(text, user_id)

    @staticmethod
    async def send_schedule_result(task_name: str, result: str, user_id: str = "") -> bool:
        """Send a scheduled task completion notification."""
        text = f"✅ 定时任务完成\n\n📌 {task_name}\n\n{result[:500]}"
        return await WeChatNotification.send(text, user_id)

    @staticmethod
    async def send_email_summary(summary: str, user_id: str = "") -> bool:
        """Send an email digest summary."""
        text = f"📬 邮件摘要\n\n{summary[:800]}"
        return await WeChatNotification.send(text, user_id)

    @staticmethod
    async def send_image(image_path: str, user_id: str = "") -> bool:
        """Send an image file to a WeChat user."""
        from pathlib import Path

        client = None
        try:
            from crabagent.serve.scheduler import get_scheduler

            sched = get_scheduler()
            loop = getattr(sched, "_wechat_loop", None)
            if loop and loop._running and loop.client._context_store:
                client = loop.client
        except Exception:
            pass

        if not client:
            client = await get_authenticated_client()
        if not client:
            logger.debug("[WeChatNotify] Not logged in — skipping image send")
            return False

        try:
            if not user_id:
                if client._context_store:
                    user_id = next(iter(client._context_store))
                else:
                    cfg = await load_config()
                    if cfg.notify_target_user and cfg.cached_context_token:
                        user_id = cfg.notify_target_user
                        client._context_store[user_id] = cfg.cached_context_token
                    else:
                        return False

            return await client.send_image(to_user=user_id, image_path=Path(image_path))
        except Exception as e:
            logger.error("[WeChatNotify] send_image failed: %s", e)
            return False
        finally:
            try:
                if client and (not client._http or not client._http.is_closed):
                    pass  # keep alive if from loop
            except Exception:
                pass

    @staticmethod
    async def send_file(file_path: str, user_id: str = "") -> bool:
        """Send a file attachment to a WeChat user."""
        from pathlib import Path

        client = None
        try:
            from crabagent.serve.scheduler import get_scheduler

            sched = get_scheduler()
            loop = getattr(sched, "_wechat_loop", None)
            if loop and loop._running and loop.client._context_store:
                client = loop.client
        except Exception:
            pass

        if not client:
            client = await get_authenticated_client()
        if not client:
            return False

        try:
            if not user_id:
                if client._context_store:
                    user_id = next(iter(client._context_store))
                else:
                    cfg = await load_config()
                    if cfg.notify_target_user and cfg.cached_context_token:
                        user_id = cfg.notify_target_user
                        client._context_store[user_id] = cfg.cached_context_token
                    else:
                        return False

            return await client.send_file(to_user=user_id, file_path=Path(file_path))
        except Exception as e:
            logger.error("[WeChatNotify] send_file failed: %s", e)
            return False
