from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    from crabagent.serve.services.auth import register_user

    if len(req.username) < 2 or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Username must be >= 2 chars, password >= 6 chars")

    user = await register_user(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")
    return UserResponse(id=user.id, username=user.username, role=user.role)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    from crabagent.serve.services.auth import authenticate_user, create_access_token

    user = await authenticate_user(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


class UpdateUserRequest(BaseModel):
    locale: str | None = None


@router.patch("/user")
async def update_user(
    req: UpdateUserRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.locale is not None:
        user.locale = req.locale
        await db.commit()
    return {"status": "ok", "locale": user.locale}
