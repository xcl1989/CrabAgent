"""Middleware framework for the agent loop.

Provides a lightweight extension protocol with three hook points:
- ``on_conversation_start``: fired once when an AgentContext is about to run
- ``before_llm_call``: fired before every LLM completion (may rewrite messages)
- ``on_conversation_end``: fired once after the run finishes (success or error)

Middlewares are optional; ``AgentContext.middlewares`` may be ``None``. The
main loop in :mod:`crabagent.core.agent.loop` keeps a fallback path that
mirrors the original behavior when no chain is attached.

This is intentionally a thin layer: it does not split the streaming / retry /
tool-call-merging core of ``run_agent``. Heavy logic stays out of the hot
path; only well-isolated hooks (compression, reflection, auto-title) live
here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from crabagent.core.agent.context import AgentContext

logger = logging.getLogger(__name__)


@runtime_checkable
class Middleware(Protocol):
    """Hook contract. Implement only the methods you care about; the
    ``MiddlewareChain`` tolerates missing methods (they become no-ops)."""

    name: str

    async def on_conversation_start(self, context: AgentContext) -> None:  # noqa: ARG002
        ...

    async def before_llm_call(
        self,
        context: AgentContext,  # noqa: ARG002
        messages: list[dict],  # noqa: ARG002
    ) -> list[dict]: ...

    async def on_conversation_end(self, context: AgentContext) -> None:  # noqa: ARG002
        ...


class MiddlewareChain:
    """Ordered list of middlewares; tolerates partial implementations."""

    def __init__(self, middlewares: list | None = None):
        self._middlewares: list = list(middlewares or [])

    @property
    def middlewares(self) -> list:
        return list(self._middlewares)

    def add(self, middleware) -> None:
        self._middlewares.append(middleware)

    async def run_start(self, context) -> None:
        for mw in self._middlewares:
            try:
                hook = getattr(mw, "on_conversation_start", None)
                if hook is None:
                    continue
                result = hook(context)
                if isinstance(result, Awaitable):
                    await result
            except Exception:
                logger.exception(
                    "middleware %s.on_conversation_start failed",
                    getattr(mw, "name", type(mw).__name__),
                )

    async def run_before_llm(self, context, messages: list[dict]) -> list[dict]:
        current = messages
        for mw in self._middlewares:
            try:
                hook = getattr(mw, "before_llm_call", None)
                if hook is None:
                    continue
                result = hook(context, current)
                if isinstance(result, Awaitable):
                    result = await result
                if result is not None:
                    current = result
            except Exception:
                logger.exception(
                    "middleware %s.before_llm_call failed",
                    getattr(mw, "name", type(mw).__name__),
                )
        return current

    async def run_end(self, context) -> None:
        for mw in reversed(self._middlewares):
            try:
                hook = getattr(mw, "on_conversation_end", None)
                if hook is None:
                    continue
                result = hook(context)
                if isinstance(result, Awaitable):
                    await result
            except Exception:
                logger.exception(
                    "middleware %s.on_conversation_end failed",
                    getattr(mw, "name", type(mw).__name__),
                )


__all__ = ["Middleware", "MiddlewareChain"]
