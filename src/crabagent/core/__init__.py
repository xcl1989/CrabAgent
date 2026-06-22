import logging

import litellm

logger = logging.getLogger(__name__)


def configure_litellm() -> None:
    """Centralised litellm initialisation for all entry points (CLI + Serve)."""
    from crabagent.core.config import settings
    from crabagent.core.provider_store import CHATGPT_IMAGE_MODELS, CHATGPT_MODELS

    litellm.set_verbose = False
    litellm.num_retries = 0  # disable litellm's built-in retry — we handle retries in loop.py
    litellm.request_timeout = settings.llm_request_timeout
    litellm.drop_params = True
    litellm.suppress_debug_info = True

    # Register ChatGPT subscription models in litellm's model_cost dict.
    # These models have no per-token cost (they use subscription quota), but litellm
    # requires them to be registered or it raises "model not mapped" errors.
    for m in CHATGPT_MODELS:
        key = f"chatgpt/{m}"
        if key not in litellm.model_cost:
            litellm.model_cost[key] = {
                "max_tokens": 128_000,
                "max_input_tokens": 270_000,
                "output_cost_per_token": 0.0,
                "input_cost_per_token": 0.0,
                "mode": "responses",
                "litellm_provider": "chatgpt",
            }

    # Register ChatGPT subscription image models in litellm's model_cost.
    for m in CHATGPT_IMAGE_MODELS:
        key = f"chatgpt/{m}"
        if key not in litellm.model_cost:
            litellm.model_cost[key] = {
                "input_cost_per_token": 0.0,
                "output_cost_per_token": 0.0,
                "mode": "image_generation",
                "litellm_provider": "chatgpt",
            }

    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)
    logger.debug(
        "litellm configured: retries=0 (handled in loop), timeout=%ds, %d chatgpt models + %d image models registered",
        settings.llm_request_timeout,
        len(CHATGPT_MODELS),
        len(CHATGPT_IMAGE_MODELS),
    )


import crabagent.core.agent.tools.bash  # noqa: F401
import crabagent.core.agent.tools.edit  # noqa: F401
import crabagent.core.agent.tools.glob  # noqa: F401
import crabagent.core.agent.tools.grep  # noqa: F401
import crabagent.core.agent.tools.image  # noqa: F401
import crabagent.core.agent.tools.memory  # noqa: F401
import crabagent.core.agent.tools.office  # noqa: F401
import crabagent.core.agent.tools.read  # noqa: F401
import crabagent.core.agent.tools.shared  # noqa: F401
import crabagent.core.agent.tools.web  # noqa: F401
import crabagent.core.agent.tools.write  # noqa: F401
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.loop import run_agent
from crabagent.core.agent.tools.registry import registry as tool_registry
from crabagent.core.config import settings

__all__ = ["settings", "AgentContext", "run_agent", "tool_registry"]
