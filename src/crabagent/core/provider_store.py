from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from crabagent.core.database import ProviderConfig, async_session_factory

logger = logging.getLogger(__name__)


def _get_fernet():
    from cryptography.fernet import Fernet

    from crabagent.core.config import settings

    return Fernet(settings.get_encryption_key().encode())


def encrypt_api_key(api_key: str) -> str:
    return _get_fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted


def _is_encrypted(value: str) -> bool:
    try:
        _get_fernet().decrypt(value.encode())
        return True
    except Exception:
        return False


@dataclass
class ProviderInfo:
    name: str
    display_name: str
    provider_type: str
    api_key: str
    base_url: str
    is_default: bool
    enabled: bool
    extra: dict[str, Any]


CHATGPT_MODELS = [
    # Current generation (verified working on Plus 2026-07)
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    # Pro-only models (require ChatGPT Pro subscription)
    "gpt-5.5-pro",
    "gpt-5.4-pro",
    # Legacy models (may still work on older accounts)
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.3-instant",
    "gpt-5.3-chat-latest",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
]

CHATGPT_IMAGE_MODELS = [
    "image-2",
    "gpt-image-2",
    "chatgpt-image-latest",
]


PROVIDER_CATALOG: dict[str, dict] = {
    "chatgpt": {
        "base_url": "",
        "display_name": "ChatGPT 订阅 (Plus/Pro)",
        "auth_type": "oauth",
        "models": CHATGPT_MODELS,
    },
    "opencode-go": {"base_url": "https://opencode.ai/zen/go/v1", "display_name": "OpenCode Go"},
    "openai": {"base_url": "https://api.openai.com/v1", "display_name": "OpenAI"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "display_name": "Anthropic"},
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "display_name": "智谱 GLM",
        "variants": [
            {"id": "standard", "display_name": "标准版", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
            {"id": "coding", "display_name": "Coding Plan", "base_url": "https://open.bigmodel.cn/api/coding/paas/v4"},
        ],
    },
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "display_name": "DeepSeek"},
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "display_name": "MiniMax",
        "variants": [
            {"id": "cn", "display_name": "国内版", "base_url": "https://api.minimax.chat/v1"},
            {"id": "intl", "display_name": "国际版", "base_url": "https://api.minimaxi.com/v1"},
        ],
    },
    "volcengine": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "display_name": "火山引擎"},
    "bailian": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "display_name": "阿里百炼"},
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "display_name": "Kimi (Moonshot AI)",
        "variants": [
            {"id": "standard", "display_name": "Moonshot 开放平台", "base_url": "https://api.moonshot.cn/v1"},
            {"id": "coding", "display_name": "Kimi Code Plan", "base_url": "https://api.kimi.com/coding/v1"},
        ],
    },
}


def resolve_catalog_variant(provider_type: str, variant_id: str | None) -> str | None:
    entry = PROVIDER_CATALOG.get(provider_type)
    if not entry or not variant_id:
        return None
    for v in entry.get("variants", []):
        if v["id"] == variant_id:
            return v["base_url"]
    return None


def _to_info(row: ProviderConfig) -> ProviderInfo:
    try:
        extra = json.loads(row.extra) if row.extra else {}
    except json.JSONDecodeError:
        extra = {}
    return ProviderInfo(
        name=row.name,
        display_name=row.display_name,
        provider_type=row.provider_type,
        api_key=decrypt_api_key(row.api_key),
        base_url=row.base_url,
        is_default=row.is_default,
        enabled=row.enabled,
        extra=extra,
    )


def _no_default_rows() -> int:
    return (
        update(ProviderConfig)
        .where(ProviderConfig.is_default == True)  # noqa: E712
        .values(is_default=False)
    )


async def get_default_provider() -> ProviderInfo | None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.is_default == True,  # noqa: E712
                ProviderConfig.enabled == True,  # noqa: E712
            )
        )
        row = result.scalar_one_or_none()
        return _to_info(row) if row else None


async def get_provider(name: str) -> ProviderInfo | None:
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig).where(ProviderConfig.name == name))
        row = result.scalar_one_or_none()
        return _to_info(row) if row else None


async def list_providers() -> list[ProviderInfo]:
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig).order_by(ProviderConfig.id))
        return [_to_info(row) for row in result.scalars().all()]


async def create_provider(
    name: str,
    provider_type: str,
    api_key: str,
    display_name: str = "",
    base_url: str = "",
    is_default: bool = False,
    extra: dict[str, Any] | None = None,
) -> ProviderInfo:
    async with async_session_factory() as session:
        if is_default:
            await session.execute(_no_default_rows())
        cfg = ProviderConfig(
            name=name,
            display_name=display_name or name,
            provider_type=provider_type,
            api_key=encrypt_api_key(api_key),
            base_url=base_url,
            is_default=is_default,
            extra=json.dumps(extra or {}),
        )
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
        return _to_info(cfg)


async def set_default_provider(name: str) -> bool:
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig).where(ProviderConfig.name == name))
        row = result.scalar_one_or_none()
        if not row:
            return False
        await session.execute(_no_default_rows())
        await session.execute(update(ProviderConfig).where(ProviderConfig.name == name).values(is_default=True))
        await session.commit()
        return True


async def update_provider(name: str, **kwargs) -> ProviderInfo | None:
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig).where(ProviderConfig.name == name))
        row = result.scalar_one_or_none()
        if not row:
            return None
        if kwargs.get("is_default"):
            await session.execute(_no_default_rows())
        for key, value in kwargs.items():
            if value is not None and hasattr(row, key):
                if key == "api_key":
                    value = encrypt_api_key(value)
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _to_info(row)


async def migrate_plaintext_keys():
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig))
        rows = result.scalars().all()
        migrated = 0
        for row in rows:
            if not _is_encrypted(row.api_key):
                row.api_key = encrypt_api_key(row.api_key)
                migrated += 1
        if migrated:
            await session.commit()
            logger.info(f"Migrated {migrated} provider API keys to encrypted storage")


async def delete_provider(name: str) -> bool:
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderConfig).where(ProviderConfig.name == name))
        row = result.scalar_one_or_none()
        if not row:
            return False
        await session.delete(row)
        await session.commit()
        return True


def build_litellm_params(provider: ProviderInfo, proxy: str = "") -> dict[str, Any]:
    """Build litellm connection params for a provider."""
    if provider.provider_type == "chatgpt":
        params: dict[str, Any] = {}
    else:
        params = {"api_key": provider.api_key}
        if provider.base_url:
            params["api_base"] = provider.base_url
            params["custom_llm_provider"] = "openai"
    if proxy:
        params["proxy"] = proxy
    return params


async def resolve_litellm_params(provider: ProviderInfo) -> dict[str, Any]:
    from crabagent.core.proxy import resolve_llm_proxy

    proxy = await resolve_llm_proxy(provider)
    return build_litellm_params(provider, proxy)


def resolve_model_for_provider(provider: ProviderInfo, model: str) -> str:
    if "/" in model:
        return model
    if provider.provider_type == "chatgpt":
        return f"chatgpt/{model}"
    return f"openai/{model}"


async def fetch_models(provider_name: str) -> list[str]:
    p = await get_provider(provider_name)
    if not p:
        return []
    base = p.base_url.rstrip("/")
    try:
        import httpx

        from crabagent.core.proxy import resolve_llm_proxy

        proxy = await resolve_llm_proxy(p)
        client_kwargs = {"timeout": 15.0}
        if proxy:
            client_kwargs["proxy"] = proxy
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {p.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        logger.warning("Failed to fetch models for provider %s", provider_name, exc_info=True)
        return []
