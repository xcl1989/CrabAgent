import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import User
from crabagent.serve.api.auth import UpdateUserRequest, update_user
from crabagent.serve.deps import _user_cache


@pytest.mark.asyncio
async def test_update_locale_persists_detached_cached_user(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'locale.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            user = User(username="locale-user", password_hash="hash", locale="en")
            db.add(user)
            await db.commit()
        _user_cache[user.id] = (0, user)
        async with sessions() as db:
            result = await update_user(UpdateUserRequest(locale="zh-CN"), user, db)
        assert result["locale"] == "zh-CN"
        assert user.id not in _user_cache
        async with sessions() as db:
            assert (await db.get(User, user.id)).locale == "zh-CN"
    finally:
        _user_cache.pop(user.id, None)
        await engine.dispose()
