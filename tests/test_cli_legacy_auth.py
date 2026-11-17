from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.auth_utils import hash_password
from crabagent.core.database import User, get_db
from crabagent.serve.api.auth import router


@pytest.mark.asyncio
async def test_login_blocks_only_historical_cli_credentials(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    legacy_hash = hash_password("cli")
    custom_hash = hash_password("a-new-password")
    async with sessions() as db:
        db.add_all([
            User(id=1, username="cli_user", password_hash=legacy_hash, role="admin", enabled=True),
            User(id=2, username="__cli__", password_hash=legacy_hash, role="user", enabled=True),
            User(id=3, username="other", password_hash=legacy_hash, role="user", enabled=True),
        ])
        await db.commit()

    async def override_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for username in ("cli_user", "__cli__"):
                response = await client.post("/auth/login", json={"username": username, "password": "cli"})
                assert response.status_code == 401
            response = await client.post("/auth/login", json={"username": "other", "password": "cli"})
            assert response.status_code == 200
            async with sessions() as db:
                users = (await db.execute(select(User).order_by(User.id))).scalars().all()
                assert [(u.id, u.role, u.enabled, u.password_hash) for u in users] == [
                    (1, "admin", True, legacy_hash),
                    (2, "user", True, legacy_hash),
                    (3, "user", True, legacy_hash),
                ]
                users[0].password_hash = custom_hash
                await db.commit()
            response = await client.post(
                "/auth/login", json={"username": "cli_user", "password": "a-new-password"}
            )
            assert response.status_code == 200
            response = await client.post("/auth/login", json={"username": "cli_user", "password": "cli"})
            assert response.status_code == 401
    finally:
        await engine.dispose()
