from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import User, get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


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

    user = await get_user_by_id(db, user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")

    return user
