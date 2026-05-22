from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
