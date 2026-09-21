"""Tests for the resumable CJK FTS sync and the app_settings raw-SQL contract.

Regression guard for the startup freeze: sync_index used to issue one giant
`DELETE FROM messages_fts_cjk` + version write in a single transaction whose
app_settings writes omitted the NOT NULL ``updated_at`` column. The whole
transaction rolled back after ~30s of write-lock, blocking new sessions and
message sends, and repeated on every restart.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database as db_module
from crabagent.core.fts import sync_index

_SCHEMA = [
    """CREATE TABLE app_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key VARCHAR(100) UNIQUE NOT NULL,
        value TEXT DEFAULT '',
        updated_at DATETIME
    )""",
    """CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT DEFAULT '',
        compressed BOOLEAN DEFAULT 0,
        role VARCHAR(20) DEFAULT 'user'
    )""",
    "CREATE VIRTUAL TABLE messages_fts_cjk USING fts5(content, tokenize='unicode61')",
]


@pytest.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for stmt in _SCHEMA:
            await conn.execute(text(stmt))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed_messages(factory, rows: list[tuple[str, str]]) -> None:
    async with factory() as db:
        for role, content in rows:
            await db.execute(
                text("INSERT INTO messages (content, compressed, role) VALUES (:c, 0, :r)"),
                {"c": content, "r": role},
            )
        await db.commit()


async def _get_setting(factory, key: str):
    async with factory() as db:
        result = await db.execute(text("SELECT value, updated_at FROM app_settings WHERE key = :k"), {"k": key})
        return result.fetchone()


async def test_legacy_migration_commits_version_and_cursor_with_updated_at(session_factory):
    """Version bump must persist (with NOT NULL updated_at) instead of rolling back."""
    await _seed_messages(session_factory, [("user", "你好世界"), ("assistant", "这是一个测试回答")])
    # Legacy index rows from the previous format (must be purged in chunks).
    async with session_factory() as db:
        await db.execute(text("INSERT INTO messages_fts_cjk(rowid, content) VALUES (1, 'legacy junk')"))
        await db.commit()

    processed = await sync_index(batch_size=2, idle_delay=0, purge_chunk=1)

    assert processed == 2
    version = await _get_setting(session_factory, "fts_cjk_index_version")
    cursor = await _get_setting(session_factory, "fts_cjk_index_cursor")
    assert version is not None and version[0] == "2" and version[1] is not None
    assert cursor is not None and cursor[1] is not None

    async with session_factory() as db:
        # Legacy junk gone; both live messages re-indexed with CJK tokens.
        rows = (await db.execute(text("SELECT content FROM messages_fts_cjk"))).fetchall()
    contents = [r[0] for r in rows]
    assert "legacy junk" not in contents
    assert len([c for c in contents if "你好" in c or "世界" in c]) >= 1


async def test_sync_resumes_from_cursor_after_restart(session_factory):
    """A second run (simulated restart) must only process new messages."""
    await _seed_messages(session_factory, [("user", "第一条消息"), ("assistant", "第一条回答")])
    first = await sync_index(batch_size=10, idle_delay=0)
    assert first == 2

    await _seed_messages(session_factory, [("user", "重启后的新消息")])
    second = await sync_index(batch_size=10, idle_delay=0)
    assert second == 1

    cursor = await _get_setting(session_factory, "fts_cjk_index_cursor")
    assert cursor[0] == "3"


async def test_batches_yield_to_busy_callback(session_factory):
    """The is_busy callback must be honoured between batches (lock released)."""
    await _seed_messages(session_factory, [("user", f"消息编号 {i}") for i in range(5)])
    calls = {"n": 0}

    def busy():
        calls["n"] += 1
        return calls["n"] <= 2  # busy for the first checks, then idle

    processed = await sync_index(batch_size=2, idle_delay=0, is_busy=busy)
    assert processed == 5
    assert calls["n"] >= 2


async def test_scheduler_process_lock_persists_updated_at(session_factory):
    """The scheduler's cross-process lock writes app_settings via raw SQL too.

    It must set the NOT NULL updated_at column, otherwise every lock
    acquisition fails with IntegrityError and dedup breaks.
    """
    from crabagent.serve.scheduler import SchedulerService

    sched = SchedulerService.__new__(SchedulerService)  # skip __init__ (no real scheduler)
    sched._own_pid = 424242

    assert await sched._acquire_process_lock("test_lock", ttl_seconds=60) is True

    row = await _get_setting(session_factory, "_lock:test_lock")
    assert row is not None
    assert row[0].startswith("424242:")
    assert row[1] is not None  # updated_at must be set

    # Re-acquiring our own lock succeeds (heartbeat path).
    assert await sched._acquire_process_lock("test_lock", ttl_seconds=60) is True


async def test_interactive_write_tracker_counts_only_api_writes():
    """Interactive-write tracking: only /api/* writes bump the busy counter."""
    import asyncio
    from types import SimpleNamespace

    from crabagent.serve.app import InteractiveWriteTrackerMiddleware

    state = SimpleNamespace(interactive_busy=0)
    seen = []
    release_write = asyncio.Event()

    async def next_app(scope, receive, send):
        seen.append((scope.get("method"), scope.get("path")))
        if scope.get("method") == "POST" and scope.get("path") == "/api/sessions":
            await release_write.wait()  # hold the write in flight

    mw = InteractiveWriteTrackerMiddleware(next_app, state_holder=state)

    async def noop_receive():
        return {"type": "http.request"}

    async def noop_send(message):
        pass

    write_task = asyncio.ensure_future(
        mw({"type": "http", "method": "POST", "path": "/api/sessions"}, noop_receive, noop_send)
    )
    await asyncio.sleep(0.01)
    assert state.interactive_busy == 1  # write in flight → background must pause

    # Concurrent reads pass straight through and never change the counter.
    await mw({"type": "http", "method": "GET", "path": "/api/events"}, noop_receive, noop_send)
    assert state.interactive_busy == 1

    release_write.set()
    await write_task
    assert state.interactive_busy == 0  # released in finally

    await mw({"type": "http", "method": "POST", "path": "/auth/login"}, noop_receive, noop_send)
    assert state.interactive_busy == 0  # non-/api paths are not tracked

    assert seen == [
        ("POST", "/api/sessions"),
        ("GET", "/api/events"),
        ("POST", "/auth/login"),
    ]
