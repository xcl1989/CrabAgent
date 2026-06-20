"""Unified proxy resolution module.

Provides a single entry point for resolving HTTP/HTTPS proxy URLs across
all network-dependent components in CrabAgent.

Three-tier priority system:
  L3 (highest): Provider-level proxy — stored in ProviderConfig.extra
  L2:           Category-level proxy — stored in app_settings
  L1 (lowest):  Global proxy — stored in app_settings
  Fallback:     Environment variable CRAB_WEB_PROXY
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crabagent.core.provider_store import ProviderInfo

logger = logging.getLogger(__name__)


async def _get_setting(key: str) -> str | None:
    """Read a value from the app_settings table (async)."""
    try:
        from sqlalchemy import select

        from crabagent.core.database import AppSetting, async_session_factory

        async with async_session_factory() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.key == key))
            row = result.scalar_one_or_none()
            return row.value if row else None
    except Exception:
        logger.debug("Failed to read setting '%s'", key, exc_info=True)
        return None


async def resolve_llm_proxy(provider: ProviderInfo | None = None) -> str:
    """Resolve proxy URL for LLM calls.

    Priority:
      1. Provider.extra["proxy_enabled"] == True → use Provider.extra["proxy_url"]
         (if proxy_url is empty, fall back to global llm_proxy / proxy)
      2. If provider.proxy_enabled is False or not set → return "" (direct connection)

    This means ONLY providers that explicitly opt-in will use a proxy.
    """
    if provider:
        extra = provider.extra or {}
        if not extra.get("proxy_enabled"):
            # Provider did not opt-in → direct connection
            return ""
        # Provider opted in
        proxy_url = (extra.get("proxy_url") or "").strip()
        if proxy_url:
            return proxy_url
        # proxy_enabled but no url → fall back to global settings
        global_llm = await _get_setting("llm_proxy")
        if global_llm:
            return global_llm
        global_proxy = await _get_setting("proxy")
        if global_proxy:
            return global_proxy

    return ""


async def resolve_category_proxy(category: str) -> str:
    """Resolve proxy URL for non-LLM categories (web, browser, misc).

    Priority:
      1. Category-specific setting (e.g. "web_proxy", "browser_proxy")
      2. Global proxy setting ("proxy")
      3. Environment variable fallback (settings.web_proxy)
    """
    # Category-specific
    cat_proxy = await _get_setting(f"{category}_proxy")
    if cat_proxy:
        return cat_proxy

    # Global
    global_proxy = await _get_setting("proxy")
    if global_proxy:
        return global_proxy

    # Environment variable fallback
    from crabagent.core.config import settings

    return settings.web_proxy or ""


async def get_httpx_kwargs(category: str = "misc") -> dict:
    """Return httpx AsyncClient kwargs with proxy if configured."""
    proxy = await resolve_category_proxy(category)
    return {"proxy": proxy} if proxy else {}
