import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from crabagent.core import database
from crabagent.core.wechat.message import WeChatMessageLoop


@pytest.mark.asyncio
async def test_process_lock_survives_poll_stop_until_dispatch_finishes(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=SimpleNamespace(notify_target_user="", cached_context_token="")),
    )

    async def poll(_):
        await asyncio.sleep(100)

    client = SimpleNamespace(_context_store={}, get_updates=AsyncMock(side_effect=poll))
    loop = WeChatMessageLoop(client)
    await loop.start()
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    loop._track_dispatch(task)
    stopping = asyncio.create_task(loop.stop())
    await asyncio.sleep(0.05)
    code = (
        "import sys; from crabagent.core.wechat.process_lock import acquire_process_lock; "
        "lock=acquire_process_lock(sys.argv[1])"
    )
    path = os.path.realpath(engine.url.database) + ".wechat.lock"
    assert subprocess.run([sys.executable, "-c", code, path], capture_output=True).returncode != 0
    release.set()
    await stopping
    assert subprocess.run([sys.executable, "-c", code, path], capture_output=True).returncode == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_immediate_stop_releases_lock(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=SimpleNamespace(notify_target_user="", cached_context_token="")),
    )

    async def poll(_):
        await asyncio.sleep(100)

    loop = WeChatMessageLoop(SimpleNamespace(_context_store={}, get_updates=AsyncMock(side_effect=poll)))
    await loop.start()
    await loop.stop()
    assert loop._lock_file is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelling_stop_does_not_cancel_drain(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=SimpleNamespace(notify_target_user="", cached_context_token="")),
    )

    async def poll(_):
        await asyncio.sleep(100)

    loop = WeChatMessageLoop(SimpleNamespace(_context_store={}, get_updates=AsyncMock(side_effect=poll)))
    await loop.start()
    release = asyncio.Event()
    loop._track_dispatch(asyncio.create_task(release.wait()))
    stopping = asyncio.create_task(loop.stop())
    await asyncio.sleep(0.01)
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert loop._lock_file is not None
    release.set()
    await loop._task
    assert loop._lock_file is None
    await engine.dispose()


def test_windows_backend_locks_first_byte_and_closes_on_contention(tmp_path, monkeypatch):
    import errno
    from unittest.mock import Mock

    from crabagent.core.wechat import process_lock

    calls = []
    fake = SimpleNamespace(LK_NBLCK=2, locking=lambda fd, mode, count: calls.append((mode, count)))
    monkeypatch.setattr(process_lock, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    lock = process_lock.acquire_process_lock(str(tmp_path / "lock"))
    assert calls == [(2, 1)]
    assert lock.tell() == 0
    lock.close()
    fake.locking = Mock(side_effect=OSError(errno.EACCES, "locked"))
    with pytest.raises(RuntimeError, match="Another WeChat"):
        process_lock.acquire_process_lock(str(tmp_path / "lock"))


def test_unexpected_lock_error_is_not_reported_as_contention(tmp_path, monkeypatch):
    import errno
    from unittest.mock import Mock

    from crabagent.core.wechat import process_lock

    fake = SimpleNamespace(LK_NBLCK=2, locking=Mock(side_effect=OSError(errno.EIO, "disk error")))
    monkeypatch.setattr(process_lock, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    with pytest.raises(OSError) as exc:
        process_lock.acquire_process_lock(str(tmp_path / "lock"))
    assert exc.value.errno == errno.EIO
