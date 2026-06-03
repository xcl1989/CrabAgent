from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.auth_utils import hash_password, verify_password
from crabagent.core.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_user_by_username(db: AsyncSession, username: str):
    from crabagent.core.database import User

    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int):
    from crabagent.core.database import User

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def register_user(db: AsyncSession, username: str, password: str):
    from crabagent.core.database import User

    existing = await get_user_by_username(db, username)
    if existing:
        return None

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="user",
        enabled=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, username: str, password: str):
    user = await get_user_by_username(db, username)
    if not user or not user.enabled:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
