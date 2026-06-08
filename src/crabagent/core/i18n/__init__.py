"""Lightweight i18n module for CrabAgent.

Supports:
- Tool description translation (for LLM)
- System prompt localization
- User-facing message translation
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_LOCALE_DIR = Path(__file__).parent
_translations: dict[str, dict] = {}

# Weekday names indexed by locale -> weekday number (0=Monday)
_WEEKDAY_NAMES: dict[str, dict[int, str]] = {
    "zh-CN": {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"},
    "en": {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"},
}

# System prompt templates keyed by locale
_SYSTEM_PROMPTS: dict[str, str] = {}

# Locale instruction appended as second system message
_LOCALE_INSTRUCTIONS: dict[str, str] = {}

# Tool return message templates
_TOOL_MESSAGES: dict[str, dict[str, str]] = {}


def _load(locale: str) -> dict:
    """Load translation file for a locale."""
    if locale not in _translations:
        path = _LOCALE_DIR / f"{locale}.json"
        if path.exists():
            _translations[locale] = json.loads(path.read_text("utf-8"))
        else:
            _translations[locale] = {}
    return _translations[locale]


def translate_tool(tool_name: str, locale: str) -> dict[str, Any] | None:
    """Get translated tool description and parameter descriptions.

    Returns dict with keys: description, params (dict of param_name -> description)
    or None if no translation exists for this tool+locale.
    """
    data = _load(locale)
    tools = data.get("tools", {})
    return tools.get(tool_name)


def get_system_prompt_template(locale: str) -> str | None:
    """Get the localized system prompt prefix template."""
    data = _load(locale)
    return data.get("system_prompt", {}).get("prefix")


def get_locale_instruction(locale: str) -> str | None:
    """Get the language instruction for the second system message."""
    data = _load(locale)
    return data.get("system_prompt", {}).get("locale_instruction")


def get_tool_message(key: str, locale: str) -> str:
    """Get a user-facing tool return message by key."""
    data = _load(locale)
    messages = data.get("messages", {})
    # Fall back to English if key not found in target locale
    if key not in messages:
        en_data = _load("en")
        messages = en_data.get("messages", {})
    return messages.get(key, key)


def t(key: str, locale: str = "en", **kwargs) -> str:
    """Get a translated string by dot-notation key.

    Falls back to English if key not found in target locale.
    Supports str.format() kwargs for interpolation.
    """
    data = _load(locale)
    parts = key.split(".")
    node: Any = data
    for p in parts:
        if isinstance(node, dict):
            node = node.get(p)
        else:
            node = None
            break

    if not isinstance(node, str):
        # Fall back to English
        en_data = _load("en")
        node = en_data
        for p in parts:
            if isinstance(node, dict):
                node = node.get(p)
            else:
                node = None
                break

    if isinstance(node, str):
        return node.format(**kwargs) if kwargs else node
    return key
