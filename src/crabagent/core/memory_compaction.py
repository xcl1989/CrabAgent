"""Bound automatic memory growth with a recoverable local archive."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select, text

logger = logging.getLogger(__name__)


async def compact_memories(
    user_id: int, *, high_water: int = 600, target: int = 300, protected_id: int | None = None
) -> int:
    """Archive lower-priority memories when a user's count reaches the high-water mark.

    SQLite's write lock covers selection, durable archive creation, and deletion.
    Failure before commit leaves the active database unchanged.
    """
    from crabagent.core.database import AgentMemory, MemoryEmbedding, async_session_factory

    # Model and embedding calls must happen outside the SQLite write transaction.
    async with async_session_factory() as db:
        current_count = (await db.execute(select(func.count()).select_from(AgentMemory).where(
            AgentMemory.user_id == user_id
        ))).scalar_one()
    if current_count < high_water:
        return 0
    from crabagent.core.memory_batch_merge import semantic_consolidate

    for _ in range(20):
        result = await semantic_consolidate(user_id)
        if result.get("status") != "ok":
            logger.warning("Semantic consolidation did not complete for user %s: %s", user_id, result.get("reason"))
            return 0
        if not result.get("merged"):
            break

    async with async_session_factory() as db:
        if db.bind.dialect.name != "sqlite":
            logger.warning("Automatic memory compaction requires SQLite; user=%s", user_id)
            return 0
        await db.execute(text("BEGIN IMMEDIATE"))
        count = (await db.execute(select(func.count()).select_from(AgentMemory).where(
            AgentMemory.user_id == user_id
        ))).scalar_one()
        if count <= target:
            return 0
        rows = (await db.execute(select(AgentMemory).where(AgentMemory.user_id == user_id))).scalars().all()

        def score(row):
            # User-created records, enduring preferences and importance take precedence.
            return (row.id == protected_id, row.source == "user", row.memory_type == "user_preference",
                    row.importance or 0, row.access_count or 0, row.updated_at or datetime.min, row.id)

        removed = sorted(rows, key=score, reverse=True)[target:]
        ids = [row.id for row in removed]
        embeddings = (await db.execute(select(MemoryEmbedding).where(
            MemoryEmbedding.memory_id.in_(ids)
        ))).scalars().all()
        def serialize(row):
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

        directory = Path.home() / ".crabagent" / "memory-archives"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, archive = tempfile.mkstemp(prefix=f"user-{user_id}-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "user_id": user_id,
                           "memories": [serialize(row) for row in removed],
                           "embeddings": [serialize(row) for row in embeddings]},
                          stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            await db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(ids)))
            await db.execute(delete(AgentMemory).where(AgentMemory.user_id == user_id, AgentMemory.id.in_(ids)))
            await db.commit()
        except BaseException:
            # Keep any completed archive even if the transaction rolls back.
            logger.exception("Memory compaction failed; archive=%s", archive)
            raise
        logger.info("Archived %s memories for user %s to %s", len(ids), user_id, archive)
        return len(ids)


def list_archives(user_id: int) -> list[dict]:
    directory = Path.home() / ".crabagent" / "memory-archives"
    archives = []
    home = Path.home() / ".crabagent"
    paths = list(directory.glob(f"user-{user_id}-*.json"))
    paths += list(home.glob("memory-archive-*.json")) + list(home.glob("memory-cleanup-*.json"))
    for path in sorted(paths, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.is_symlink() or not isinstance(data.get("memories"), list):
                continue
            owned = [row for row in data["memories"] if row.get("user_id") == user_id]
            if owned and (data.get("user_id", user_id) == user_id):
                archives.append({"name": path.name, "count": len(owned)})
        except (OSError, ValueError, TypeError):
            logger.warning("Unable to read memory archive %s", path.name)
    return archives


def read_archive(user_id: int, name: str) -> dict:
    directory = Path.home() / ".crabagent" / "memory-archives"
    import re

    if Path(name).name != name:
        raise ValueError("Invalid archive name")
    if re.fullmatch(rf"user-{user_id}-[a-zA-Z0-9_-]+\.json", name):
        path = directory / name
    elif re.fullmatch(r"memory-(?:archive|cleanup)-[0-9]{8}-[0-9]{6}\.json", name):
        path = Path.home() / ".crabagent" / name
    else:
        raise ValueError("Invalid archive name")
    if path.is_symlink():
        raise ValueError("Invalid archive")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("user_id", user_id) != user_id or not isinstance(data.get("memories"), list):
        raise ValueError("Invalid archive owner or contents")
    return {**data, "memories": [row for row in data["memories"] if row.get("user_id") == user_id]}


async def restore_archived_memory(user_id: int, name: str, memory_id: int) -> str:
    """Restore one archived row without overwriting any current memory."""
    from crabagent.core.database import AgentMemory, async_session_factory

    data = read_archive(user_id, name)
    rows = [row for row in data["memories"] if row.get("id") == memory_id and row.get("user_id") == user_id]
    if len(rows) != 1:
        raise ValueError("Memory not found in archive")
    row = rows[0]
    async with async_session_factory() as db:
        if db.bind.dialect.name != "sqlite":
            raise ValueError("Restoration currently requires SQLite")
        await db.execute(text("BEGIN IMMEDIATE"))
        existing = await db.execute(select(AgentMemory).where(
            AgentMemory.user_id == user_id, AgentMemory.key == row["key"],
            AgentMemory.memory_type == row["memory_type"],
            func.coalesce(AgentMemory.scope, "") == (row.get("scope") or ""),
            func.coalesce(AgentMemory.workspace_path, "") == (row.get("workspace_path") or ""),
            func.coalesce(AgentMemory.agent_name, "") == (row.get("agent_name") or ""),
        ))
        if existing.scalars().first():
            return "exists"
        values = {col.name: row[col.name] for col in AgentMemory.__table__.columns
                  if col.name in row and col.name not in ("id", "created_at", "updated_at")}
        restored = AgentMemory(**values)
        db.add(restored)
        await db.flush()
        restored_id = restored.id
        await db.commit()
    await compact_memories(user_id, protected_id=restored_id)
    return "restored"
