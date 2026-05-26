from __future__ import annotations

import time

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_user_cache: dict[int, tuple[float, User]] = {}
_USER_CACHE_TTL = 60.0


async def get_owned_conversation(db: AsyncSession, session_id: str, user: User):
    from crabagent.serve.services import conversation as conv_svc

    conv = await conv_svc.get_conversation(db, session_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your session")
    return conv


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    from crabagent.serve.services.auth import decode_access_token, get_user_by_id

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    now = time.time()
    cached = _user_cache.get(user_id)
    if cached and now - cached[0] < _USER_CACHE_TTL:
        return cached[1]

    user = await get_user_by_id(db, user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")

    _user_cache[user_id] = (now, user)
    return user
