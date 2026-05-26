from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User
from crabagent.core.provider_store import (
    PROVIDER_CATALOG,
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    set_default_provider,
    update_provider,
)
from crabagent.serve.deps import get_current_user

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderResponse(BaseModel):
    name: str
    display_name: str
    type: str
    is_default: bool
    enabled: bool
    base_url: str
    api_key_preview: str


class CatalogEntry(BaseModel):
    type: str
    display_name: str
    base_url: str


class CreateProviderRequest(BaseModel):
    name: str
    type: str
    api_key: str
    display_name: str = ""
    base_url: str = ""
    is_default: bool = False


class UpdateProviderRequest(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


def _to_response(p) -> ProviderResponse:
    return ProviderResponse(
        name=p.name,
        display_name=p.display_name,
        type=p.provider_type,
        is_default=p.is_default,
        enabled=p.enabled,
        base_url=p.base_url,
        api_key_preview=_mask_key(p.api_key),
    )


@router.get("/catalog", response_model=list[CatalogEntry])
async def get_catalog(user: User = Depends(get_current_user)):
    return [
        CatalogEntry(type=k, display_name=v["display_name"], base_url=v["base_url"])
        for k, v in PROVIDER_CATALOG.items()
    ]


@router.get("", response_model=list[ProviderResponse])
async def list_provider_endpoints(user: User = Depends(get_current_user)):
    providers = await list_providers()
    return [_to_response(p) for p in providers]


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider_endpoint(req: CreateProviderRequest, user: User = Depends(get_current_user)):
    existing = await get_provider(req.name)
    if existing:
        raise HTTPException(status_code=409, detail="Provider already exists")

    catalog = PROVIDER_CATALOG.get(req.type)
    base_url = req.base_url or (catalog["base_url"] if catalog else "")
    display_name = req.display_name or (catalog["display_name"] if catalog else req.name)

    p = await create_provider(
        name=req.name,
        provider_type=req.type,
        api_key=req.api_key,
        display_name=display_name,
        base_url=base_url,
        is_default=req.is_default,
    )
    return _to_response(p)


@router.patch("/{name}", response_model=ProviderResponse)
async def update_provider_endpoint(name: str, req: UpdateProviderRequest, user: User = Depends(get_current_user)):
    existing = await get_provider(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if req.is_default:
        await set_default_provider(name)
        updates.pop("is_default", None)

    p = await update_provider(name, **updates)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _to_response(p)


@router.delete("/{name}", status_code=204)
async def delete_provider_endpoint(name: str, user: User = Depends(get_current_user)):
    ok = await delete_provider(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")


@router.get("/{name}/models")
async def get_provider_models(name: str, user: User = Depends(get_current_user)):
    p = await get_provider(name)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{p.base_url}/models",
                headers={"Authorization": f"Bearer {p.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")

    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if mid:
            models.append({"id": mid, "owned_by": m.get("owned_by", "")})
    return models
