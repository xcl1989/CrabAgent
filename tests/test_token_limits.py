from crabagent.core.agent.token_limits import get_model_token_limit, DEFAULT_MODEL_TOKEN_LIMITS


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

    def test_unknown_model_fallback(self):
        assert get_model_token_limit("totally-unknown-model") == 128_000

    def test_all_models_have_positive_limit(self):
        for model, limit in DEFAULT_MODEL_TOKEN_LIMITS.items():
            assert limit > 0, f"{model} has non-positive limit {limit}"
