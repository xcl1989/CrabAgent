"""Lightweight i18n module for CrabAgent.

Supports:
- Tool description translation (for LLM)
- System prompt localization
- User-facing message translation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _resolve_locale_dir() -> Path:
    """Resolve the directory containing i18n JSON files.

    Works in three environments:
    1. Normal Python install — Path(__file__).parent
    2. PyInstaller frozen — sys._MEIPASS / crabagent / core / i18n
    3. importlib.resources fallback
    """
    # Primary: same directory as this module
    d = Path(__file__).parent
    if (d / "en.json").exists():
        return d

    # Frozen / PyInstaller: try _MEIPASS-based path
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for candidate in (
            Path(meipass) / "crabagent" / "core" / "i18n",
            Path(meipass) / "core" / "i18n",
        ):
            if (candidate / "en.json").exists():
                return candidate

    # Fallback: importlib.resources
    try:
        import importlib.resources as _res

        ref = _res.files("crabagent.core.i18n")
        if hasattr(ref, "is_dir") and ref.is_dir():
            return Path(str(ref))
    except Exception:
        pass

    # Last resort: return default path even if files may not exist
    return d


_LOCALE_DIR = _resolve_locale_dir()
_translations: dict[str, dict] = {}
# Track file modification times so we can auto-reload when JSON is updated
_translation_mtimes: dict[str, float] = {}

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
    """Load translation file for a locale.

    Automatically reloads if the JSON file has been modified on disk
    (e.g., after a code update without server restart).
    """
    path = _LOCALE_DIR / f"{locale}.json"
    if path.exists():
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        cached_mtime = _translation_mtimes.get(locale, -1)
        if locale not in _translations or mtime != cached_mtime:
            _translations[locale] = json.loads(path.read_text("utf-8"))
            _translation_mtimes[locale] = mtime
    elif locale not in _translations:
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
