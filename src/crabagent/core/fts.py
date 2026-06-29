"""FTS5 full-text search helpers with jieba Chinese word segmentation.

Provides:
- ``index_message()`` — sync a single message to the CJK FTS5 index
- ``rebuild_index()`` — batch rebuild the entire index from scratch
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_JIEBA_LOADED = False

# Global progress tracking — accessible from health endpoint
_rebuild_in_progress = False
_rebuild_total = 0
_rebuild_done = 0


def get_rebuild_status() -> dict:
    """Return current FTS rebuild status for health/readiness checks."""
    return {
        "in_progress": _rebuild_in_progress,
        "total": _rebuild_total,
        "done": _rebuild_done,
    }


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


def _segment_batch_sync(rows: list) -> list[dict]:
    """Synchronous helper: segment a batch of (id, content) rows.

    Designed to be called via ``asyncio.to_thread()`` so jieba's CPU-intensive
    work doesn't block the event loop.
    """
    batch: list[dict] = []
    for row in rows:
        tokens = segment(row[1] or "")  # row[1] = content
        if tokens.strip():
            batch.append({"id": row[0], "content": tokens})  # row[0] = id
    return batch


async def index_message(message_id: int, content: str) -> None:
    """Index a single message into the CJK FTS5 table.

    Args:
        message_id: The ``messages.id`` value (becomes FTS5 rowid).
        content: Raw message text — will be jieba-tokenized automatically.
    """
    from sqlalchemy import text as sa_text

    from crabagent.core.database import async_session_factory

    # Run segmentation in thread pool to avoid blocking the event loop
    tokens = await asyncio.to_thread(segment, content)
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

    **Concurrency design**: read and write use completely separate DB sessions
    so SQLite write locks are held only for the brief moment of each batch
    INSERT+commit (milliseconds), never during jieba segmentation (seconds).

    Timeline per batch:
        1. jieba segment 500 rows in thread pool → NO write lock held
        2. Open write session, INSERT 500 rows, commit → write lock held ~5ms
        3. Close session, yield to event loop → write lock released

    This guarantees API requests (save messages, create sessions, etc.) are
    never blocked for more than a few milliseconds.

    Args:
        workspace: Optional workspace path to scope the rebuild (if None, all users).

    Returns:
        Number of messages indexed.
    """
    global _rebuild_in_progress, _rebuild_total, _rebuild_done

    from sqlalchemy import select, text as sa_text

    from crabagent.core.database import Message, async_session_factory

    # Warm up jieba dictionary in a background thread (first import is slow ~1-2s)
    await asyncio.to_thread(_ensure_jieba)

    BATCH_SIZE = 500

    # ── Phase 1: Read all messages (read-only session, no write lock) ──
    async with async_session_factory() as db_read:
        stmt = select(Message.id, Message.content).where(
            Message.compressed == False  # noqa: E712
        ).order_by(Message.id)
        if workspace:
            from crabagent.core.database import Conversation
            stmt = stmt.join(
                Conversation, Message.conversation_id == Conversation.id
            ).where(Conversation.workspace == str(workspace))

        result = await db_read.execute(stmt)
        rows = result.fetchall()
        total_msgs = len(rows)

    _rebuild_in_progress = True
    _rebuild_total = total_msgs
    _rebuild_done = 0

    if total_msgs == 0:
        _rebuild_in_progress = False
        return 0

    # ── Phase 2: Truncate FTS index (separate session, commit immediately) ──
    async with async_session_factory() as db_write:
        await db_write.execute(sa_text("DELETE FROM messages_fts_cjk"))
        await db_write.commit()  # Release write lock immediately

    # ── Phase 3: Batch insert — open+close session per batch ──
    # Each batch: jieba in thread (no lock held) → INSERT+commit (lock held ~ms)
    count = 0
    insert_sql = sa_text(
        "INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"
    )
    for i in range(0, total_msgs, BATCH_SIZE):
        batch_rows = rows[i : i + BATCH_SIZE]
        # Run jieba segmentation in thread pool — NO DB lock held during this
        batch = await asyncio.to_thread(_segment_batch_sync, batch_rows)
        if batch:
            # Quick INSERT + commit — write lock held for milliseconds only
            async with async_session_factory() as db_write:
                await db_write.execute(insert_sql, batch)
                await db_write.commit()
        count += len(batch_rows)
        _rebuild_done = count
        logger.info("[FTS] Indexed %d / %d messages...", count, total_msgs)
        # Yield to event loop so pending API requests can be processed
        await asyncio.sleep(0)

    _rebuild_in_progress = False
    logger.info("[FTS] Rebuild complete: %d messages indexed", count)
    return count
