from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.agent.agents import invalidate_cache
from crabagent.core.database import AgentProfile, User, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentProfileResponse(BaseModel):
    id: int
    name: str
    display_name: str
    role: str
    goal: str
    backstory: str
    model: str
    allow_delegation: bool
    enabled: bool
    created_at: str


class UpdateAgentRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    model: str | None = None
    allow_delegation: bool | None = None
    enabled: bool | None = None


def _to_response(a: AgentProfile) -> AgentProfileResponse:
    return AgentProfileResponse(
        id=a.id,
        name=a.name,
        display_name=a.display_name or a.name,
        role=a.role,
        goal=a.goal,
        backstory=a.backstory or "",
        model=a.model or "",
        allow_delegation=a.allow_delegation,
        enabled=a.enabled,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


@router.get("", response_model=list[AgentProfileResponse])
async def list_agent_profiles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentProfile).order_by(AgentProfile.name))
    return [_to_response(r) for r in result.scalars().all()]


@router.patch("/{agent_name}", response_model=AgentProfileResponse)
async def update_agent_profile(
    agent_name: str,
    req: UpdateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.name == agent_name))
    profile = result.scalar_one_or_none()
    if not profile:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Agent not found")

    if req.display_name is not None:
        profile.display_name = req.display_name
    if req.role is not None:
        profile.role = req.role
    if req.goal is not None:
        profile.goal = req.goal
    if req.backstory is not None:
        profile.backstory = req.backstory
    if req.model is not None:
        profile.model = req.model
    if req.allow_delegation is not None:
        profile.allow_delegation = req.allow_delegation
    if req.enabled is not None:
        profile.enabled = req.enabled

    await db.commit()
    await db.refresh(profile)
    invalidate_cache()
    return _to_response(profile)
