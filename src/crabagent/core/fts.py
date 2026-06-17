"""FTS5 full-text search helpers with jieba Chinese word segmentation.

Provides:
- ``index_message()`` — sync a single message to the CJK FTS5 index
- ``rebuild_index()`` — batch rebuild the entire index from scratch
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_JIEBA_LOADED = False


def _ensure_jieba():
    """Lazy-import jieba so the module can be imported without it installed."""
    global _JIEBA_LOADED
    if not _JIEBA_LOADED:
        import jieba  # noqa: F401 — loads dictionary on first import
        _JIEBA_LOADED = True


def segment(text: str) -> str:
    """Tokenize text with jieba and return space-joined tokens.

    Handles both Chinese and English text. English words are left intact,
    Chinese characters are segmented into words separated by spaces.
    """
    _ensure_jieba()
    import jieba
    return " ".join(jieba.cut(text or "", cut_all=False))


async def index_message(message_id: int, content: str) -> None:
    """Index a single message into the CJK FTS5 table.

    Args:
        message_id: The ``messages.id`` value (becomes FTS5 rowid).
        content: Raw message text — will be jieba-tokenized automatically.
    """
    from sqlalchemy import text as sa_text

    from crabagent.core.database import async_session_factory

    tokens = segment(content)
    async with async_session_factory() as db:
        # Delete old index entry if any (idempotent)
        try:
            await db.execute(sa_text(
                "INSERT INTO messages_fts_cjk(messages_fts_cjk, rowid, content) "
                "VALUES('delete', :id, '')"
            ), {"id": message_id})
        except Exception:
            pass
        if tokens.strip():
            await db.execute(sa_text(
                "INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"
            ), {"id": message_id, "content": tokens})
        await db.commit()


async def rebuild_index(workspace: str | Path | None = None) -> int:
    """Rebuild the entire CJK FTS5 index from all messages.

    Args:
        workspace: Optional workspace path to scope the rebuild (if None, all users).

    Returns:
        Number of messages indexed.
    """
    from sqlalchemy import select, text as sa_text

    from crabagent.core.database import Message, async_session_factory

    # Warm up jieba (first import loads dictionary)
    _ensure_jieba()

    count = 0
    BATCH_SIZE = 500

    async with async_session_factory() as db:
        # Truncate FTS5 index
        await db.execute(sa_text("DELETE FROM messages_fts_cjk"))

        # Stream all non-compressed messages
        stmt = select(Message.id, Message.content).where(
            Message.compressed == False  # noqa: E712
        ).order_by(Message.id)
        if workspace:
            from crabagent.core.database import Conversation
            stmt = stmt.join(Conversation, Message.conversation_id == Conversation.id).where(
                Conversation.workspace == str(workspace)
            )

        result = await db.execute(stmt)
        rows = result.fetchall()
        batch: list[dict] = []
        for row in rows:
            tokens = segment(row.content or "")
            if tokens.strip():
                batch.append({"id": row.id, "content": tokens})
            count += 1
            if len(batch) >= BATCH_SIZE:
                await db.execute(sa_text(
                    "INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"
                ), batch)
                batch.clear()
                logger.info("[FTS] Indexed %d messages so far...", count)
        if batch:
            await db.execute(sa_text(
                "INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"
            ), batch)
        await db.commit()

    logger.info("[FTS] Rebuild complete: %d messages indexed", count)
    return count
