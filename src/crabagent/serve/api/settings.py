from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.config import settings as app_settings
from crabagent.core.database import AppSetting, get_db
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSetting))
    return {row.key: row.value for row in result.scalars().all()}


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


@router.put("")
async def update_settings(
    req: UpdateSettingsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for key, value in req.settings.items():
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    await db.commit()

    result = await db.execute(select(AppSetting))
    return {row.key: row.value for row in result.scalars().all()}


class TestSearxngRequest(BaseModel):
    url: str


@router.post("/test-searxng")
async def test_searxng(
    req: TestSearxngRequest,
    user=Depends(get_current_user),
):
    import httpx

    url = req.url.rstrip("/") + "/search?q=test&format=json&categories=general"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            count = len(data.get("results", []))
            return {"success": True, "result_count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/skills")
async def list_skills(user=Depends(get_current_user)):
    """返回当前已发现的所有 skill 列表。"""
    from crabagent.core.agent.skill.loader import discover_skills

    skill_dirs = app_settings.skill_discovery_dirs()
    skills = discover_skills(skill_dirs)
    return [
        {
            "name": s.name,
            "description": s.description,
            "location": str(s.location),
            "auxiliary_files": [
                str(f.relative_to(s.location)) if f.is_relative_to(s.location) else str(f)
                for f in s.auxiliary_files
            ],
        }
        for s in sorted(skills.values(), key=lambda s: s.name)
    ]


@router.get("/skills/{name}")
async def get_skill_detail(name: str, user=Depends(get_current_user)):
    """返回指定 skill 的完整内容。"""
    from crabagent.core.agent.skill.loader import discover_skills

    skill_dirs = app_settings.skill_discovery_dirs()
    skills = discover_skills(skill_dirs)
    skill = skills.get(name)
    if not skill:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {
        "name": skill.name,
        "description": skill.description,
        "content": skill.content,
        "location": str(skill.location),
        "auxiliary_files": [
            str(f.relative_to(skill.location)) if f.is_relative_to(skill.location) else str(f)
            for f in skill.auxiliary_files
        ],
    }
