"""Provider quota/balance query API.

Unified endpoint to query remaining quota/balance across supported providers:
  - deepseek: GET /user/balance (cash balance)
  - zhipu:    GET /api/monitor/usage/quota/limit (Coding Plan token limits)
  - chatgpt:  already handled by chatgpt_auth.py (/chatgpt/account)
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from crabagent.core.database import User
from crabagent.core.provider_store import get_provider
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


async def _query_deepseek_balance(api_key: str) -> dict:
    """Query DeepSeek balance via GET /user/balance.

    Note: base_url in catalog is https://api.deepseek.com/v1,
    but the balance endpoint lives at the root domain.
    """
    url = "https://api.deepseek.com/user/balance"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        return resp.json()


async def _query_zhipu_quota(base_url: str, api_key: str) -> dict:
    """Query Zhipu GLM Coding Plan quota via monitor API.

    Auth is the raw API key directly (no Bearer prefix).
    Domain extracted from base_url (strip /v4 path).
    """
    parsed = urlparse(base_url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    url = f"{domain}/api/monitor/usage/quota/limit"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": api_key})
        resp.raise_for_status()
        return resp.json()


@router.get("/quota")
async def get_provider_quota(
    name: str = Query(..., description="Provider name"),
    user: User = Depends(get_current_user),
):
    """Query quota/balance for a specific provider by name."""
    provider = await get_provider(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    if provider.provider_type == "deepseek":
        try:
            raw = await _query_deepseek_balance(provider.api_key)
        except Exception as e:
            logger.warning("DeepSeek balance query failed: %s", e)
            raise HTTPException(status_code=502, detail=f"DeepSeek balance query failed: {e}") from e

        balance_infos = raw.get("balance_infos", [])
        summary = {
            "is_available": raw.get("is_available", False),
            "balances": [
                {
                    "currency": b.get("currency", ""),
                    "total": b.get("total_balance", "0"),
                    "granted": b.get("granted_balance", "0"),
                    "topped_up": b.get("topped_up_balance", "0"),
                }
                for b in balance_infos
            ],
        }
        return {"provider_type": "deepseek", "raw": raw, "summary": summary}

    elif provider.provider_type == "zhipu":
        try:
            raw = await _query_zhipu_quota(provider.base_url, provider.api_key)
        except Exception as e:
            logger.warning("Zhipu quota query failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Zhipu quota query failed: {e}") from e

        data = raw.get("data", {}) if isinstance(raw, dict) else {}
        limits = data.get("limits", [])
        token_limits = []
        time_limit = None
        for lim in limits:
            if lim.get("type") == "TOKENS_LIMIT":
                token_limits.append({
                    "percentage": lim.get("percentage", 0),
                    "unit": lim.get("unit"),
                    "number": lim.get("number"),
                    "nextResetTime": lim.get("nextResetTime"),
                    "label": f"{lim.get('number', '?')}H" if lim.get("unit") == 3 else "WEEK",
                })
            elif lim.get("type") == "TIME_LIMIT":
                time_limit = {
                    "percentage": lim.get("percentage", 0),
                    "usage": lim.get("usage", 0),
                    "currentValue": lim.get("currentValue", 0),
                    "remaining": lim.get("remaining", 0),
                    "nextResetTime": lim.get("nextResetTime"),
                    "usageDetails": lim.get("usageDetails", []),
                }

        summary = {
            "level": data.get("level", ""),
            "token_limits": token_limits,
            "time_limit": time_limit,
        }
        return {"provider_type": "zhipu", "raw": raw, "summary": summary}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Quota query not supported for provider type '{provider.provider_type}'",
        )
