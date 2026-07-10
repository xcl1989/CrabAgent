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
    AgentRun,
    Conversation,
    User,
    agent_memory_delete,
    agent_memory_get_by_agent,
    get_db,
    run_record_get,
    run_record_growth,
    run_record_list,
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
    tool_permissions: dict[str, str]
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
    tool_permissions: dict[str, str] | None = None


class UpdateAgentRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    model: str | None = None
    icon: str | None = None
    allow_delegation: bool | None = None
    enabled: bool | None = None
    tool_permissions: dict[str, str] | None = None


def _to_response(a: AgentProfile) -> AgentProfileResponse:
    import json as _json

    tools_list = []
    if a.tools:
        try:
            tools_list = _json.loads(a.tools)
        except Exception:
            pass
    tool_perms = {}
    if a.tool_permissions:
        try:
            tool_perms = _json.loads(a.tool_permissions)
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
        tool_permissions=tool_perms,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


@router.get("", response_model=list[AgentProfileResponse])
async def list_agent_profiles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentProfile).where(AgentProfile.name != "__default__").order_by(AgentProfile.name)
    )
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
        tool_permissions=_json.dumps(req.tool_permissions) if req.tool_permissions else "{}",
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
    if req.tool_permissions is not None:
        import json as _json

        profile.tool_permissions = _json.dumps(req.tool_permissions)

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


@router.get("/tools")
async def list_tools():
    from crabagent.core.agent.tools.registry import registry as _registry

    return _registry.tool_info_list()


class DefaultToolPermissionsRequest(BaseModel):
    tool_permissions: dict[str, str]


@router.get("/default-tool-permissions")
async def get_default_tool_permissions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _json

    result = await db.execute(select(AgentProfile).where(AgentProfile.name == "__default__"))
    profile = result.scalar_one_or_none()
    if not profile:
        return {"tool_permissions": {}}
    tp = {}
    if profile.tool_permissions:
        try:
            tp = _json.loads(profile.tool_permissions)
        except Exception:
            pass
    return {"tool_permissions": tp}


@router.put("/default-tool-permissions")
async def set_default_tool_permissions(
    req: DefaultToolPermissionsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json as _json

    result = await db.execute(select(AgentProfile).where(AgentProfile.name == "__default__"))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = AgentProfile(
            user_id=user.id,
            name="__default__",
            display_name="Default Permissions",
            role="default",
            goal="default",
            is_default=True,
            enabled=True,
        )
        db.add(profile)
    profile.tool_permissions = _json.dumps(req.tool_permissions)
    await db.commit()
    invalidate_cache()
    return {"tool_permissions": req.tool_permissions}


_SUMMARY_PRIORITY = {"waiting": 0, "error": 1, "working": 2, "thinking": 3, "completed": 4, "idle": 5}
_SUMMARY_TRANSIENT_SECONDS = 6.0


def _summary_message(status: str, count: int, target: dict | None) -> str:
    if status == "waiting":
        kind = target.get("request_type") if target else ""
        if kind == "input":
            return "需要你补充一点信息" if count == 1 else f"{count} 个会话等待你的输入"
        return "需要你确认" if count == 1 else f"{count} 个会话等待你的确认"
    if status == "error":
        return "有 1 个任务遇到了问题" if count == 1 else f"有 {count} 个任务遇到了问题"
    if status == "working":
        tool_name = (target or {}).get("tool_name", "")
        if count == 1 and tool_name:
            return f"正在使用 {tool_name} 处理任务"
        return "1 个会话正在执行任务" if count == 1 else f"{count} 个会话正在执行任务"
    if status == "thinking":
        return "正在整理思路" if count == 1 else f"{count} 个会话正在整理思路"
    if status == "completed":
        return "任务完成，做得漂亮！"
    return "随时可以开始"


@router.get("/monitor/summary")
async def monitor_summary(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the highest-priority, actionable state across a user's sessions."""
    now = time.time()
    active_agents = getattr(request.app.state, "active_agents", {})
    attention = getattr(request.app.state, "agent_attention", {})
    session_ids = [sid for sid, info in active_agents.items() if info.get("user_id") == user.id]

    from crabagent.serve.api.confirm import get_pending_confirms_for_session
    from crabagent.serve.api.input import get_pending_for_session

    candidates: list[dict] = []
    for session_id in session_ids:
        info = active_agents[session_id]
        pending_input = get_pending_for_session(session_id)
        pending_confirm = get_pending_confirms_for_session(session_id)
        request_type = "input" if pending_input else "confirm" if pending_confirm else ""
        status = "waiting" if request_type else info.get("pet_status", "thinking")
        if status == "waiting" and not request_type:
            status = "thinking"
        if status not in _SUMMARY_PRIORITY:
            status = "thinking"
        candidates.append(
            {
                "status": status,
                "session_id": session_id,
                "updated_at": info.get("waiting_since") or info.get("updated_at") or info.get("started_at", now),
                "request_type": request_type or None,
                "tool_name": info.get("tool_name", ""),
            }
        )

    # Completed and errored sessions are intentionally short-lived feedback states.
    for session_id, info in list(attention.items()):
        if info.get("user_id") != user.id:
            continue
        if now - info.get("updated_at", 0) > _SUMMARY_TRANSIENT_SECONDS:
            attention.pop(session_id, None)
            continue
        candidates.append(
            {
                "status": info.get("status", "completed"),
                "session_id": session_id,
                "updated_at": info.get("updated_at", now),
                "request_type": None,
                "tool_name": "",
            }
        )

    if not candidates:
        return {
            "status": "idle",
            "priority": _SUMMARY_PRIORITY["idle"],
            "count": 0,
            "message": _summary_message("idle", 0, None),
            "target": None,
            "updated_at": now,
        }

    highest_priority = min(_SUMMARY_PRIORITY[item["status"]] for item in candidates)
    matching = [item for item in candidates if _SUMMARY_PRIORITY[item["status"]] == highest_priority]
    # Resolve ties to the longest-waiting or most recently changed actionable session.
    target = sorted(matching, key=lambda item: item["updated_at"])[0]
    rows = await db.execute(
        select(Conversation.session_id, Conversation.title).where(Conversation.session_id == target["session_id"])
    )
    row = rows.first()
    target_data = {
        "session_id": target["session_id"],
        "title": row[1] if row and row[1] else "未命名会话",
        "request_type": target["request_type"],
    }
    if target["tool_name"]:
        target_data["tool_name"] = target["tool_name"]
    status = target["status"]
    return {
        "status": status,
        "priority": highest_priority,
        "count": len(matching),
        "message": _summary_message(status, len(matching), target_data),
        "target": target_data,
        "updated_at": max(item["updated_at"] for item in matching),
    }


@router.get("/monitor")
async def monitor_agents(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("monitor_agents ENTER")
    active_agents = getattr(request.app.state, "active_agents", {})
    result = []
    now = time.time()

    from crabagent.core.agent.agents import get_all_session_subs

    # Batch-fetch workspace + title for all active sessions (single query)
    sids = [sid for sid, info in active_agents.items() if info.get("user_id") == user.id]
    session_meta: dict[str, dict] = {}
    if sids:
        from crabagent.core.database import Conversation
        rows = await db.execute(
            select(Conversation.session_id, Conversation.workspace, Conversation.title)
            .where(Conversation.session_id.in_(sids))
        )
        for row in rows.fetchall():
            session_meta[row[0]] = {"workspace": row[1] or "", "title": row[2] or ""}

    for sid, info in active_agents.items():
        if info.get("user_id") != user.id:
            continue
        meta = session_meta.get(sid, {})
        result.append(
            {
                "session_id": sid,
                "model": info.get("model", ""),
                "status": info.get("status", "unknown"),
                "started_at": info.get("started_at", 0),
                "elapsed": round(now - info.get("started_at", now), 1),
                "workspace": meta.get("workspace", ""),
                "title": meta.get("title", ""),
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

    mem_result = await db.execute(select(distinct(AgentMemory.agent_name)).where(AgentMemory.user_id == user.id))
    task_result = await db.execute(select(distinct(TaskRecord.agent_name)).where(TaskRecord.user_id == user.id))
    agent_names = set(mem_result.scalars().all()) | set(task_result.scalars().all())
    return sorted(agent_names)


@router.get("/runs")
async def list_agent_runs(
    agent_name: str | None = Query(None, description="Filter by agent name"),
    status: str | None = Query(None, description="Filter by status (running/completed/failed)"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    runs = await run_record_list(
        user_id=user.id,
        agent_name=agent_name or "",
        status=status or "",
        session_id=session_id or "",
        limit=limit,
        offset=offset,
    )
    return runs


@router.get("/runs/{run_id}")
async def get_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
):
    run = await run_record_get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return run


@router.get("/pipelines/history")
async def get_pipeline_history(
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
):
    from crabagent.core.database import _run_to_dict, async_session_factory

    async with async_session_factory() as db:
        pipelines = (
            (
                await db.execute(
                    select(AgentRun)
                    .where(AgentRun.user_id == user.id, AgentRun.agent_name == "pipeline")
                    .order_by(AgentRun.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        result = []
        for p in pipelines:
            pd = _run_to_dict(p)
            steps = (
                (await db.execute(select(AgentRun).where(AgentRun.parent_run_id == p.id).order_by(AgentRun.id.asc())))
                .scalars()
                .all()
            )
            pd["steps"] = [_run_to_dict(s) for s in steps]
            result.append(pd)
        return result


@router.get("/{agent_name}/growth")
async def get_agent_growth(
    agent_name: str,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    data = await run_record_growth(user.id, agent_name, days=days)
    return data
