import logging

import litellm

logger = logging.getLogger(__name__)


def configure_litellm() -> None:
    """Centralised litellm initialisation for all entry points (CLI + Serve)."""
    from crabagent.core.config import settings

    litellm.set_verbose = False
    litellm.num_retries = 0  # disable litellm's built-in retry — we handle retries in loop.py
    litellm.request_timeout = settings.llm_request_timeout
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)
    logger.debug("litellm configured: retries=0 (handled in loop), timeout=%ds", settings.llm_request_timeout)


import crabagent.core.agent.tools.bash  # noqa: F401
import crabagent.core.agent.tools.edit  # noqa: F401
import crabagent.core.agent.tools.glob  # noqa: F401
import crabagent.core.agent.tools.grep  # noqa: F401
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
