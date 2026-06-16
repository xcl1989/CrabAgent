from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from crabagent.core.database import User, ProviderConfig, async_session_factory
from crabagent.core.provider_store import (
    PROVIDER_CATALOG,
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    resolve_catalog_variant,
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
    extra_models: list[str] = []


class CatalogVariant(BaseModel):
    id: str
    display_name: str
    base_url: str


class CatalogEntry(BaseModel):
    type: str
    display_name: str
    base_url: str
    variants: list[CatalogVariant] = []


class CreateProviderRequest(BaseModel):
    name: str
    type: str
    api_key: str
    display_name: str = ""
    base_url: str = ""
    variant_id: str | None = None
    is_default: bool = False


class UpdateProviderRequest(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    extra_models: list[str] | None = None


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


def _to_response(p) -> ProviderResponse:
    extra_models = []
    if hasattr(p, "extra") and p.extra:
        try:
            import json
            extra = json.loads(p.extra) if isinstance(p.extra, str) else p.extra
            extra_models = extra.get("extra_models", [])
        except Exception:
            pass
    return ProviderResponse(
        name=p.name,
        display_name=p.display_name,
        type=p.provider_type,
        is_default=p.is_default,
        enabled=p.enabled,
        base_url=p.base_url,
        api_key_preview=_mask_key(p.api_key),
        extra_models=extra_models,
    )


@router.get("/catalog", response_model=list[CatalogEntry])
async def get_catalog(user: User = Depends(get_current_user)):
    return [
        CatalogEntry(
            type=k,
            display_name=v["display_name"],
            base_url=v["base_url"],
            variants=[
                CatalogVariant(id=vv["id"], display_name=vv["display_name"], base_url=vv["base_url"])
                for vv in v.get("variants", [])
            ],
        )
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
    variant_url = resolve_catalog_variant(req.type, req.variant_id)
    base_url = req.base_url or variant_url or (catalog["base_url"] if catalog else "")
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

    if req.is_default:
        await set_default_provider(name)

    # Handle extra_models — store into extra JSON
    if req.extra_models is not None:
        import json as _json
        async with async_session_factory() as session:
            result = await session.execute(
                select(ProviderConfig).where(ProviderConfig.name == name)
            )
            row = result.scalar_one_or_none()
            if row:
                try:
                    extra = _json.loads(row.extra) if row.extra else {}
                except Exception:
                    extra = {}
                extra["extra_models"] = req.extra_models
                row.extra = _json.dumps(extra)
                await session.commit()
                await session.refresh(row)
                from crabagent.core.provider_store import _to_info
                return _to_response(row)

    updates = {k: v for k, v in req.model_dump().items() if v is not None and k != "extra_models"}
    if req.is_default:
        updates.pop("is_default", None)

    p = await update_provider(name, **updates)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    # _to_response expects a ProviderConfig row, but update_provider returns ProviderInfo
    # Reconstruct response manually
    extra_models = existing.extra.get("extra_models", []) if req.extra_models is None else req.extra_models
    return ProviderResponse(
        name=p.name,
        display_name=p.display_name,
        type=p.provider_type,
        is_default=p.is_default,
        enabled=p.enabled,
        base_url=p.base_url,
        api_key_preview=_mask_key(p.api_key),
        extra_models=extra_models,
    )


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

    models = []

    # Fetch from provider API
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{p.base_url}/models",
                headers={"Authorization": f"Bearer {p.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        for m in data.get("data", []):
            mid = m.get("id", "")
            if mid:
                models.append({"id": mid, "owned_by": m.get("owned_by", "")})
    except Exception as e:
        # If API fails but we have extra_models, still return those
        if not p.extra.get("extra_models"):
            raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")

    # Merge extra_models (user-defined, not returned by API)
    existing_ids = {m["id"] for m in models}
    for mid in p.extra.get("extra_models", []):
        if mid and mid not in existing_ids:
            models.append({"id": mid, "owned_by": "custom"})

    return models
