"""Context-compression middleware.

Wraps :func:`crabagent.core.agent.compress.compress_context` into a
``Middleware`` so that the agent loop can call it uniformly via the
``MiddlewareChain``. The original function is kept for backward compatibility.

The middleware reads ``context.metadata["_llm_params"]`` and
``context.metadata["_resolved_model"]`` (stashed by ``run_agent`` on the first
iteration). If those entries are missing, it degrades to a no-op.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from crabagent.core.agent.compress import compress_context
from crabagent.core.agent.token_limits import get_model_token_limit
from crabagent.core.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CompressMiddleware:
    """Summarises older messages when total tokens approach the model limit.

    Runs on every ``before_llm_call`` hook. When the cumulative token count
    exceeds ``settings.context_compression_threshold`` of the model's window,
    delegates to :func:`compress_context`. Returns the message list unchanged
    otherwise (and on any error)."""

    name = "compress"

    async def on_conversation_start(self, context) -> None:  # noqa: ARG002
        return None

    async def before_llm_call(self, context, messages: list[dict]) -> list[dict]:
        model = context.metadata.get("_resolved_model") or context.model or "gpt-4"
        try:
            max_context = get_model_token_limit(model)
        except Exception:
            max_context = 8000
        threshold = settings.context_compression_threshold
        if context.total_tokens <= max_context * threshold:
            return messages

        llm_params = context.metadata.get("_llm_params")
        if not isinstance(llm_params, dict) or not llm_params:
            logger.debug("CompressMiddleware skipped: _llm_params not yet stashed")
            return messages

        normalized_model = model if "/" in model else f"openai/{model}"
        try:
            await compress_context(context, llm_params, normalized_model)
        except Exception:
            logger.exception("CompressMiddleware failed; keeping original messages")
        return context.messages

    async def on_conversation_end(self, context) -> None:  # noqa: ARG002
        return None


__all__ = ["CompressMiddleware"]
