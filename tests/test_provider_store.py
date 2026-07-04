from __future__ import annotations

from crabagent.core.provider_store import ProviderInfo, build_litellm_params, resolve_model_for_provider


def test_build_litellm_params_for_chatgpt_provider_omits_api_key():
    provider = ProviderInfo(
        name="gptplus",
        display_name="ChatGPT",
        provider_type="chatgpt",
        api_key="oauth-managed",
        base_url="",
        is_default=False,
        enabled=True,
        extra={},
    )

    params = build_litellm_params(provider)

    assert params == {}


def test_build_litellm_params_for_openai_compatible_provider_includes_api_key_and_base():
    provider = ProviderInfo(
        name="opencodeGO",
        display_name="OpenCode Go",
        provider_type="opencode-go",
        api_key="sk-test",
        base_url="https://example.com/v1",
        is_default=True,
        enabled=True,
        extra={},
    )

    params = build_litellm_params(provider)

    assert params == {
        "api_key": "sk-test",
        "api_base": "https://example.com/v1",
        "custom_llm_provider": "openai",
    }


def test_resolve_model_for_provider_adds_chatgpt_prefix():
    provider = ProviderInfo(
        name="gptplus",
        display_name="ChatGPT",
        provider_type="chatgpt",
        api_key="oauth-managed",
        base_url="",
        is_default=False,
        enabled=True,
        extra={},
    )

    assert resolve_model_for_provider(provider, "gpt-5.4") == "chatgpt/gpt-5.4"


def test_resolve_model_for_provider_keeps_existing_prefix():
    provider = ProviderInfo(
        name="gptplus",
        display_name="ChatGPT",
        provider_type="chatgpt",
        api_key="oauth-managed",
        base_url="",
        is_default=False,
        enabled=True,
        extra={},
    )

    assert resolve_model_for_provider(provider, "chatgpt/gpt-5.4") == "chatgpt/gpt-5.4"
