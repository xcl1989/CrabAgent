"""Transactional in-place compaction of a selected WeChat conversation.

The caller serializes turns for a sender in one process. Other processes and
non-WeChat writers must not concurrently operate on WeChat conversations.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text, update

from crabagent.core.database import AppSetting, Conversation, Message, async_session_factory
from crabagent.core.wechat.selection import key

logger = logging.getLogger(__name__)


def _snapshot(rows):
    return [
        (
            r.id,
            r.sequence,
            r.role,
            r.content,
            r.compressed,
            r.branch_id,
            r.tool_calls,
            r.tool_call_id,
            r.name,
            r.reasoning_content,
        )
        for r in rows
    ]


async def compact(account, sender, workspace, conv_id, title, model, provider_name, threshold=150):
    """Summarize an unchanged snapshot; retain all original rows on failure."""
    from crabagent.core.wechat.message import _summarize_conversation, sanitize_history_content
    from crabagent.core.wechat.selection import load

    try:
        state = await load(account, sender)
        if state.get("sessions", {}).get(workspace) != conv_id:
            return False
        async with async_session_factory() as db:
            conv = await db.get(Conversation, conv_id)
            if not conv or (conv.user_id, conv.source, conv.title, conv.workspace) != (1, "wechat", title, workspace):
                return False
            rows = list(
                (
                    await db.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv_id, Message.branch_id == "main")
                        .order_by(Message.sequence, Message.id)
                    )
                ).all()
            )
            snapshot = _snapshot(rows)
            active = [r for r in rows if not r.compressed and r.role in ("user", "assistant", "compress") and r.content]
            if len(active) <= threshold:
                return False
            history = [{"role": r.role, "content": sanitize_history_content(r.content)} for r in active]
        summary = await _summarize_conversation(history, model, provider_name)
        if not isinstance(summary, str) or not summary.strip():
            return False

        async with async_session_factory() as db:
            # SQLite's reserved write lock closes the check/commit race with other DB writers.
            if db.bind.dialect.name == "sqlite":
                await db.execute(text("BEGIN IMMEDIATE"))
            else:
                logger.warning("WeChat compaction requires SQLite; skipping")
                return False
            setting = await db.scalar(select(AppSetting).where(AppSetting.key == key(account, sender)))
            import json

            if not setting or json.loads(setting.value) != state:
                return False
            conv = await db.get(Conversation, conv_id)
            if not conv or (conv.user_id, conv.source, conv.title, conv.workspace) != (1, "wechat", title, workspace):
                return False
            current = list(
                (
                    await db.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv_id, Message.branch_id == "main")
                        .order_by(Message.sequence, Message.id)
                    )
                ).all()
            )
            if _snapshot(current) != snapshot:
                return False
            await db.execute(
                update(Message)
                .where(
                    Message.conversation_id == conv_id,
                    Message.branch_id == "main",
                    Message.compressed == False,  # noqa: E712
                )
                .values(compressed=True)
            )
            db.add(
                Message(
                    conversation_id=conv_id,
                    branch_id="main",
                    role="compress",
                    content=summary.strip(),
                    sequence=max((r.sequence for r in current), default=0) + 1,
                    compressed=False,
                )
            )
            await db.commit()
        return True
    except Exception:
        logger.warning("WeChat compaction failed; retaining original history", exc_info=True)
        return False
