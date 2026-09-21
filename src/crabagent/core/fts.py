"""Incremental CJK full-text indexing for chat messages."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_JIEBA_LOADED = False
_INDEX_VERSION = "2"
_VERSION_KEY = "fts_cjk_index_version"
_CURSOR_KEY = "fts_cjk_index_cursor"
_MAX_SOURCE_CHARS = 256_000
_MAX_INDEX_CHARS = 64_000
_DATA_IMAGE_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)

_rebuild_in_progress = False
_rebuild_total = 0
_rebuild_done = 0


def get_rebuild_status() -> dict:
    """Return progress for the low-priority incremental indexer."""
    return {"in_progress": _rebuild_in_progress, "total": _rebuild_total, "done": _rebuild_done}


def _ensure_jieba() -> None:
    global _JIEBA_LOADED
    if not _JIEBA_LOADED:
        import jieba  # noqa: F401

        _JIEBA_LOADED = True


def segment(text: str) -> str:
    """Tokenize text with jieba for FTS5."""
    _ensure_jieba()
    import jieba

    return " ".join(jieba.cut(text or "", cut_all=False))


def extract_indexable_text(content: str | None) -> str:
    """Keep only bounded human-readable text; never index image payloads."""
    if not content or len(content) > _MAX_SOURCE_CHARS:
        return ""
    text = content
    if content.lstrip().startswith("["):
        try:
            blocks = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            blocks = None
        if isinstance(blocks, list):
            text = " ".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
    text = _DATA_IMAGE_RE.sub("", text)
    return text[:_MAX_INDEX_CHARS]


def _segment_batch_sync(rows: list[tuple[int, str]]) -> list[dict]:
    batch: list[dict] = []
    for message_id, content in rows:
        text = extract_indexable_text(content)
        if text:
            tokens = segment(text)
            if tokens.strip():
                batch.append({"id": message_id, "content": tokens})
    return batch


async def _upsert_setting(db, key: str, value: str) -> None:
    """Persist an ``app_settings`` row via raw SQL.

    ``app_settings.updated_at`` is NOT NULL; every raw write must set it.
    CURRENT_TIMESTAMP is UTC, matching the ORM's ``utcnow`` default.
    """
    from sqlalchemy import text as sa_text

    await db.execute(
        sa_text(
            "INSERT INTO app_settings (key, value, updated_at) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = CURRENT_TIMESTAMP"
        ),
        {"key": key, "value": value},
    )


async def index_message(message_id: int, content: str) -> None:
    """Index one newly persisted message without retaining image data."""
    from sqlalchemy import text as sa_text

    from crabagent.core.database import async_session_factory

    text = extract_indexable_text(content)
    if not text:
        return
    tokens = await asyncio.to_thread(segment, text)
    if not tokens.strip():
        return
    async with async_session_factory() as db:
        # Re-indexing is safe when a startup catch-up overlaps a live message.
        await db.execute(sa_text("DELETE FROM messages_fts_cjk WHERE rowid = :id"), {"id": message_id})
        await db.execute(
            sa_text("INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"),
            {"id": message_id, "content": tokens},
        )
        await db.commit()


async def sync_index(
    *,
    batch_size: int = 50,
    idle_delay: float = 0.15,
    is_busy=None,
    purge_chunk: int = 500,
) -> int:
    """Resume CJK indexing from a durable cursor instead of rebuilding on startup.

    Lock-safety rules (a startup rebuild must never block interactive writes):
      - Every write transaction is short (one batch) and commits immediately.
      - The legacy-index purge (on version change) deletes in small chunks,
        never one giant transaction that would roll back and retry forever.
      - Between transactions we yield to interactive requests via ``idle_delay``
        and the ``is_busy`` callback.
    """
    global _rebuild_in_progress, _rebuild_total, _rebuild_done

    from sqlalchemy import text as sa_text

    from crabagent.core.database import async_session_factory

    async def _yield_to_interactive():
        while is_busy and is_busy():
            await asyncio.sleep(1)
        await asyncio.sleep(idle_delay)

    await asyncio.to_thread(_ensure_jieba)
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                sa_text("SELECT key, value FROM app_settings WHERE key IN (:version, :cursor)"),
                {"version": _VERSION_KEY, "cursor": _CURSOR_KEY},
            )
        ).fetchall()
        state = {row[0]: row[1] for row in rows}
        purge_legacy = state.get(_VERSION_KEY) != _INDEX_VERSION
        if purge_legacy:
            # Mark the migration in a SHORT transaction first: legacy rows are
            # purged chunk-by-chunk below, so a crash mid-purge no longer rolls
            # back (and repeats) a multi-second full-table DELETE.
            await _upsert_setting(db, _VERSION_KEY, _INDEX_VERSION)
            await _upsert_setting(db, _CURSOR_KEY, "0")
            await db.commit()
            cursor = 0
        else:
            try:
                cursor = int(state.get(_CURSOR_KEY, "0"))
            except (TypeError, ValueError):
                cursor = 0
        pending = (
            await db.execute(
                sa_text("""
            SELECT count(*) FROM messages
            WHERE id > :cursor AND compressed = 0
              AND role IN ('user', 'assistant', 'compress')
        """),
                {"cursor": cursor},
            )
        ).scalar() or 0

    if purge_legacy:
        # One-time migration removes legacy entries that include tool
        # output/base64. Done in committed chunks so each holds the SQLite
        # write lock for only a few ms; rows are rebuilt from cursor 0 below.
        purged = 0
        while True:
            await _yield_to_interactive()
            async with async_session_factory() as db:
                result = await db.execute(
                    sa_text(
                        "DELETE FROM messages_fts_cjk WHERE rowid IN (SELECT rowid FROM messages_fts_cjk LIMIT :chunk)"
                    ),
                    {"chunk": purge_chunk},
                )
                await db.commit()
                deleted = result.rowcount or 0
            if not deleted:
                break
            purged += deleted
        if purged:
            logger.info("[FTS] Purged %d legacy CJK rows in chunks", purged)

    _rebuild_in_progress = pending > 0
    _rebuild_total = pending
    _rebuild_done = 0
    processed = 0
    while True:
        while is_busy and is_busy():
            await asyncio.sleep(1)
        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    sa_text("""
                SELECT id, content FROM messages
                WHERE id > :cursor AND compressed = 0
                  AND role IN ('user', 'assistant', 'compress')
                ORDER BY id LIMIT :limit
            """),
                    {"cursor": cursor, "limit": batch_size},
                )
            ).fetchall()
        if not rows:
            break

        batch = await asyncio.to_thread(_segment_batch_sync, rows)
        last_id = rows[-1][0]
        async with async_session_factory() as db:
            # Delete first so catch-up can safely overlap live incremental writes.
            for message_id, _content in rows:
                await db.execute(sa_text("DELETE FROM messages_fts_cjk WHERE rowid = :id"), {"id": message_id})
            if batch:
                await db.execute(sa_text("INSERT INTO messages_fts_cjk(rowid, content) VALUES (:id, :content)"), batch)
            await _upsert_setting(db, _CURSOR_KEY, str(last_id))
            await db.commit()
        cursor = last_id
        processed += len(rows)
        _rebuild_done = processed
        # Deliberately yield CPU and SQLite to interactive requests.
        await asyncio.sleep(idle_delay)

    _rebuild_in_progress = False
    logger.info("[FTS] Incremental CJK sync processed %d messages", processed)
    return processed


async def rebuild_index(workspace: str | Path | None = None) -> int:
    """Compatibility wrapper. Global rebuilds now use the resumable sync."""
    if workspace is not None:
        raise ValueError("Workspace-scoped CJK rebuild is no longer supported")
    return await sync_index()
