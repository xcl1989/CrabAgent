from __future__ import annotations

from crabagent.core.config import settings

DEFAULT_MODEL_TOKEN_LIMITS: dict[str, int] = {
    "deepseek-chat": 1_000_000,
    "deepseek-reasoner": 64_000,
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4.1-nano": 1_000_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_000,
    "gpt-3.5-turbo": 16_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gpt-5.5": 270_000,
    "gpt-5.5-pro": 270_000,
    "gpt-5.4": 270_000,
    "gpt-5.4-pro": 270_000,
    "gpt-5.4-mini": 270_000,
    "gpt-5.3-codex": 128_000,
    "gpt-5.3-codex-spark": 128_000,
    "gpt-5.3-instant": 128_000,
    "gpt-5.3-chat-latest": 128_000,
    "gpt-5.2-codex": 128_000,
    "gpt-5.2": 128_000,
    "gpt-5.1-codex-max": 128_000,
    "gpt-5.1-codex-mini": 128_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250115": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    "glm-4-plus": 128_000,
    "glm-5": 200_000,
    "glm-5-turbo": 200_000,
    "glm-5.1": 200_000,
    "glm-5.2": 1_000_000,
    "qwen-turbo": 1_000_000,
    "qwen-plus": 128_000,
    "qwen-max": 32_000,
    "qwen-long": 1_000_000,
    "minimax-01": 1_000_000,
}

_PREFIX_MATCH_ORDER = [
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-3-5-sonnet",
    "claude-3-haiku",
    "deepseek-v4",
    "gpt-4.1",
    "gpt-4o",
    "gpt-4-turbo",
    "glm-4",
    "glm-5",
    "qwen-",
]

_FALLBACK = 128_000

VISION_UNSUPPORTED_EXACT = {
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "o3-mini",
    "o1-mini",
    "o1-preview",
    "gpt-3.5-turbo",
    "qwen-turbo",
    "qwen-plus",
    "qwen-max",
    "qwen-long",
    "glm-4",
    "glm-4-flash",
    "glm-4-plus",
    "glm-4-long",
    "glm-5",
    "glm-5-turbo",
    "glm-5.1",
    "glm-4.5",
    "glm-4.6",
    "glm-4.7",
    "glm-5.2",
    "minimax-01",
}

VISION_UNSUPPORTED_PREFIXES = [
    "deepseek-",
    "minimax-",
    "gpt-3.5-",
    "o1-",
]


def is_vision_model(model: str) -> bool:
    clean = model.split("/", 1)[-1] if "/" in model else model
    if clean in VISION_UNSUPPORTED_EXACT:
        return False
    for prefix in VISION_UNSUPPORTED_PREFIXES:
        if clean.startswith(prefix):
            return False
    return True


def get_model_token_limit(model: str) -> int:
    clean = model.split("/", 1)[-1] if "/" in model else model

    if settings.model_token_limits and clean in settings.model_token_limits:
        return settings.model_token_limits[clean]

    if clean in DEFAULT_MODEL_TOKEN_LIMITS:
        return DEFAULT_MODEL_TOKEN_LIMITS[clean]

    for prefix in _PREFIX_MATCH_ORDER:
        if clean.startswith(prefix):
            for key, val in DEFAULT_MODEL_TOKEN_LIMITS.items():
                if key.startswith(prefix):
                    return val

    return _FALLBACK
