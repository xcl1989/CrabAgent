from types import SimpleNamespace

from crabagent.core.agent import token_limits
from crabagent.core.agent.token_limits import DEFAULT_MODEL_TOKEN_LIMITS, get_model_token_limit, is_vision_model


class TestTokenLimits:
    def test_exact_match(self):
        assert get_model_token_limit("deepseek-chat") == 1_000_000
        assert get_model_token_limit("gpt-4o") == 128_000
        assert get_model_token_limit("gpt-4") == 8_000
        assert get_model_token_limit("o3") == 200_000
        assert get_model_token_limit("qwen-turbo") == 1_000_000

    def test_prefix_match(self):
        assert get_model_token_limit("claude-sonnet-4-custom") == 200_000
        assert get_model_token_limit("gpt-4o-custom") == 128_000

    def test_litellm_prefix_stripped(self):
        assert get_model_token_limit("openai/gpt-4o") == 128_000
        assert get_model_token_limit("openai/deepseek-chat") == 1_000_000

    def test_custom_override_from_settings(self, monkeypatch):
        monkeypatch.setattr(token_limits, "settings", SimpleNamespace(model_token_limits={"gpt-4o": 999}))

        assert get_model_token_limit("gpt-4o") == 999

    def test_unknown_model_fallback(self):
        assert get_model_token_limit("totally-unknown-model") == 128_000

    def test_all_models_have_positive_limit(self):
        for model, limit in DEFAULT_MODEL_TOKEN_LIMITS.items():
            assert limit > 0, f"{model} has non-positive limit {limit}"

    def test_is_vision_model_rejects_exact_unsupported_models(self):
        assert is_vision_model("deepseek-chat") is False
        assert is_vision_model("openai/qwen-turbo") is False

    def test_is_vision_model_rejects_unsupported_prefixes(self):
        assert is_vision_model("deepseek-anything") is False
        assert is_vision_model("openai/o1-preview-extended") is False

    def test_is_vision_model_accepts_supported_models(self):
        assert is_vision_model("gpt-4o") is True
        assert is_vision_model("openai/claude-sonnet-4-20250514") is True
