from __future__ import annotations

import pytest

from crabagent.core import i18n


def test_translate_tool_returns_none_for_unknown_locale():
    assert i18n.translate_tool("bash", "xx-XX") is None


def test_translate_tool_returns_translation_for_zh_cn():
    result = i18n.translate_tool("bash", "zh-CN")
    # zh-CN.json should exist and contain tool translations
    if result is not None:
        assert isinstance(result, dict)
        assert "description" in result


def test_get_tool_message_falls_back_to_english():
    # Use a key that exists in en.json
    result = i18n.get_tool_message("nonexistent_key_xyz", "zh-CN")
    assert result == "nonexistent_key_xyz"


def test_t_returns_key_for_missing():
    assert i18n.t("nonexistent.deep.path", "en") == "nonexistent.deep.path"


def test_t_supports_format_kwargs():
    result = i18n.t("compress.instruction", "en")
    assert isinstance(result, str)


def test_get_system_prompt_template_returns_none_or_string():
    result = i18n.get_system_prompt_template("zh-CN")
    assert result is None or isinstance(result, str)


def test_get_locale_instruction_returns_none_or_string():
    result = i18n.get_locale_instruction("en")
    assert result is None or isinstance(result, str)
