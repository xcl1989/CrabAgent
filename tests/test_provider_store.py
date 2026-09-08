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

    # OpenCode Go requires a stable x-opencode-session header on every request.
    headers = params.pop("extra_headers")
    assert params == {
        "api_key": "sk-test",
        "api_base": "https://example.com/v1",
        "custom_llm_provider": "openai",
    }
    assert headers["x-opencode-session"]
    assert headers["User-Agent"].startswith("crabagent/")


def test_opencode_session_id_is_used_when_provided():
    provider = ProviderInfo(
        name="opencodeGO",
        display_name="OpenCode Go",
        provider_type="opencode-go",
        api_key="sk-test",
        base_url="https://example.com/v1",
        is_default=False,
        enabled=True,
        extra={},
    )

    params = build_litellm_params(provider, session_id="conv-123")
    headers = params["extra_headers"]

    assert headers["x-opencode-session"] == "conv-123"


def test_non_opencode_providers_have_no_extra_headers():
    provider = ProviderInfo(
        name="deepseek",
        display_name="DeepSeek",
        provider_type="deepseek",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        is_default=False,
        enabled=True,
        extra={},
    )

    assert "extra_headers" not in build_litellm_params(provider)


def test_same_type_providers_keep_separate_api_keys():
    first = ProviderInfo(
        name="zhipu-work",
        display_name="智谱 GLM",
        provider_type="zhipu",
        api_key="work-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        is_default=True,
        enabled=True,
        extra={},
    )
    second = ProviderInfo(
        name="zhipu-personal",
        display_name="智谱 GLM",
        provider_type="zhipu",
        api_key="personal-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        is_default=False,
        enabled=True,
        extra={},
    )

    assert build_litellm_params(first)["api_key"] == "work-key"
    assert build_litellm_params(second)["api_key"] == "personal-key"


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
