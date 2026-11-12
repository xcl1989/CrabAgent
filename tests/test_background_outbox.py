import pytest

from crabagent.core import database as db
from crabagent.core.agent import background_outbox
from tests.test_background_delegation import session_factory  # noqa: F401


async def test_atomic_publish_and_receipt(session_factory):
    scope = (1, "session", "main")
    async with session_factory() as conn:
        conn.add(db.BackgroundGroup(id="g", user_id=1, session_id="session", branch_id="main", status="running"))
        await conn.commit()
    async with session_factory() as conn:
        with pytest.raises(ValueError):
            await background_outbox.authorize(conn, "g", (2, "session", "main"))
        await background_outbox.authorize(conn, "g", scope)
        await conn.commit()
    async with session_factory() as conn:
        assert await background_outbox.finalize(conn, "g", "running", "succeeded")
        await conn.rollback()
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundGroup, "g")).status == "running"
        assert (await conn.get(db.BackgroundDelivery, "g")).status == "authorized"
        assert await background_outbox.finalize(conn, "g", "running", "succeeded")
        await conn.commit()
    async with session_factory() as conn:
        assert not await background_outbox.finalize(conn, "g", "running", "failed")
        assert not await background_outbox.acknowledge(conn, "g", (1, "session", "other"))
        assert await background_outbox.acknowledge(conn, "g", scope)
        await conn.commit()
        first = (await conn.get(db.BackgroundDelivery, "g")).acknowledged_at
        assert await background_outbox.acknowledge(conn, "g", scope)
        await conn.commit()
        assert (await conn.get(db.BackgroundDelivery, "g")).acknowledged_at == first


async def test_authorization_races_terminal_commit(session_factory):
    import asyncio
    scope = (1, "session", "main")
    async with session_factory() as conn:
        conn.add(db.BackgroundGroup(id="race", user_id=1, session_id="session", branch_id="main", status="running"))
        await conn.commit()
    locked = asyncio.Event()
    release = asyncio.Event()
    async def grant():
        async with session_factory() as conn:
            await background_outbox.authorize(conn, "race", scope)
            locked.set()
            await release.wait()
            await conn.commit()
    async def finish():
        await locked.wait()
        async with session_factory() as conn:
            assert await background_outbox.finalize(conn, "race", "running", "succeeded")
            await conn.commit()
    grant_task = asyncio.create_task(grant())
    finish_task = asyncio.create_task(finish())
    await locked.wait()
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(grant_task, finish_task)
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundDelivery, "race")).status == "ready"
        with pytest.raises(ValueError):
            await background_outbox.authorize(conn, "race", scope)


async def test_revoke_and_recovery_are_scoped(session_factory):
    from crabagent.core.agent import background
    scope = (1, "session", "main")
    async with session_factory() as conn:
        for group_id in ("keep", "revoke"):
            conn.add(db.BackgroundGroup(id=group_id, user_id=1, session_id="session", branch_id="main", status="running"))
        await conn.commit()
        for group_id in ("keep", "revoke"):
            await background_outbox.authorize(conn, group_id, scope)
        assert not await background_outbox.revoke(conn, "keep", (2, "session", "main"))
        assert await background_outbox.revoke(conn, "revoke", scope)
        await conn.commit()
    await background._interrupt_orphans()
    async with session_factory() as conn:
        assert (await conn.get(db.BackgroundGroup, "keep")).status == "interrupted"
        assert (await conn.get(db.BackgroundDelivery, "keep")).terminal_status == "interrupted"
        assert (await conn.get(db.BackgroundDelivery, "revoke")).status == "revoked"
