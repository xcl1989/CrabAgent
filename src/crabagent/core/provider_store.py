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


PROVIDER_CATALOG: dict[str, dict] = {
    "opencode-go": {"base_url": "https://opencode.ai/zen/go/v1", "display_name": "OpenCode Go"},
    "openai": {"base_url": "https://api.openai.com/v1", "display_name": "OpenAI"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "display_name": "Anthropic"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "display_name": "智谱 GLM"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "display_name": "DeepSeek"},
    "minimax": {"base_url": "https://api.minimax.chat/v1", "display_name": "MiniMax"},
    "volcengine": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "display_name": "火山引擎"},
    "bailian": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "display_name": "阿里百炼"},
}


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
        await session.execute(
            update(ProviderConfig).where(ProviderConfig.name == name).values(is_default=True)
        )
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


async def fetch_models(provider_name: str) -> list[str]:
    p = await get_provider(provider_name)
    if not p:
        return []
    base = p.base_url.rstrip("/")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
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
