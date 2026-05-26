from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.agent.agents import invalidate_cache
from crabagent.core.database import (
    AgentProfile,
    User,
    get_db,
    agent_memory_get_by_agent,
    agent_memory_delete,
    task_record_stats,
)
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)

DEFAULT_AGENT_NAMES = {"researcher", "analyst", "coder", "writer"}


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
    icon: str
    is_default: bool
    tools: list[str]
    created_at: str


class CreateAgentRequest(BaseModel):
    name: str
    display_name: str
    role: str
    goal: str
    backstory: str = ""
    model: str = ""
    icon: str = "🤖"
    allow_delegation: bool = True
    tools: list[str] | None = None


class UpdateAgentRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    model: str | None = None
    icon: str | None = None
    allow_delegation: bool | None = None
    enabled: bool | None = None
    tools: list[str] | None = None


def _to_response(a: AgentProfile) -> AgentProfileResponse:
    import json as _json

    tools_list = []
    if a.tools:
        try:
            tools_list = _json.loads(a.tools)
        except Exception:
            pass
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
        icon=a.icon or "",
        is_default=a.is_default or False,
        tools=tools_list,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


@router.get("", response_model=list[AgentProfileResponse])
async def list_agent_profiles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentProfile).order_by(AgentProfile.name))
    return [_to_response(r) for r in result.scalars().all()]


@router.post("", response_model=AgentProfileResponse, status_code=201)
async def create_agent_profile(
    req: CreateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = req.name.strip().lower().replace(" ", "_")
    if not name:
        raise HTTPException(status_code=400, detail="Agent name is required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Agent name too long")

    existing = await db.execute(select(AgentProfile).where(AgentProfile.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists")

    import json as _json

    profile = AgentProfile(
        user_id=user.id,
        name=name,
        display_name=req.display_name,
        role=req.role,
        goal=req.goal,
        backstory=req.backstory,
        model=req.model,
        icon=req.icon,
        allow_delegation=req.allow_delegation,
        is_default=False,
        tools=_json.dumps(req.tools) if req.tools else "",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    invalidate_cache()
    return _to_response(profile)


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
    if req.icon is not None:
        profile.icon = req.icon
    if req.allow_delegation is not None:
        profile.allow_delegation = req.allow_delegation
    if req.enabled is not None:
        profile.enabled = req.enabled
    if req.tools is not None:
        import json as _json

        profile.tools = _json.dumps(req.tools) if req.tools else ""

    await db.commit()
    await db.refresh(profile)
    invalidate_cache()
    return _to_response(profile)


@router.delete("/{agent_name}")
async def delete_agent_profile(
    agent_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.name == agent_name))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    if profile.is_default:
        raise HTTPException(status_code=403, detail="Default agents cannot be deleted. Disable them instead.")

    from sqlalchemy import delete

    await db.execute(delete(AgentProfile).where(AgentProfile.name == agent_name))
    await db.commit()
    invalidate_cache()
    return {"status": "deleted", "name": agent_name}


@router.get("/monitor")
async def monitor_agents(
    request: Request,
    user: User = Depends(get_current_user),
):
    logger.info("monitor_agents ENTER")
    active_agents = getattr(request.app.state, "active_agents", {})
    result = []
    now = time.time()

    from crabagent.core.agent.agents import get_all_session_subs

    for sid, info in active_agents.items():
        if info.get("user_id") != user.id:
            continue
        result.append(
            {
                "session_id": sid,
                "model": info.get("model", ""),
                "status": info.get("status", "unknown"),
                "started_at": info.get("started_at", 0),
                "elapsed": round(now - info.get("started_at", now), 1),
            }
        )

        for sub_id, sub_info in get_all_session_subs(sid).items():
            sub_status = sub_info.get("status", "running")
            if sub_info.get("completed_at"):
                sub_elapsed = sub_info.get("elapsed", 0)
            else:
                sub_elapsed = round(now - sub_info.get("started_at", now), 1)
            result.append(
                {
                    "session_id": sub_id,
                    "model": sub_info.get("agent_name", ""),
                    "status": sub_status,
                    "started_at": sub_info.get("started_at", 0),
                    "elapsed": sub_elapsed,
                }
            )

    logger.info("monitor_agents EXIT %d agents", len(result))
    return result


@router.get("/memory")
async def list_agent_memory(
    agent_name: str = Query(..., description="Agent name"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    memories = await agent_memory_get_by_agent(user.id, agent_name, limit=limit)
    return [
        {
            "key": m["key"],
            "category": m["category"],
            "source": m["source"],
            "content": m["content"],
            "importance": m["importance"],
            "task_category": m["task_category"],
            "access_count": m["access_count"],
            "created_at": m["created_at"].isoformat() if m["created_at"] else None,
        }
        for m in memories
    ]


@router.delete("/memory/{key:path}")
async def delete_agent_memory(
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await agent_memory_delete(user.id, key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return {"status": "deleted", "key": key}


@router.get("/stats")
async def list_agent_stats(
    agent_name: str = Query(..., description="Agent name"),
    user: User = Depends(get_current_user),
):
    stats = await task_record_stats(user.id, agent_name=agent_name)
    return stats


@router.get("/learning-agents")
async def list_learning_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import distinct

    from crabagent.core.database import AgentMemory, TaskRecord

    mem_result = await db.execute(
        select(distinct(AgentMemory.agent_name))
        .where(AgentMemory.user_id == user.id)
    )
    task_result = await db.execute(
        select(distinct(TaskRecord.agent_name))
        .where(TaskRecord.user_id == user.id)
    )
    agent_names = set(mem_result.scalars().all()) | set(task_result.scalars().all())
    return sorted(agent_names)
