from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.event import EventBus

if TYPE_CHECKING:
    from crabagent.core.agent.middlewares import MiddlewareChain


@dataclass
class AgentContext:
    workspace: Path
    messages: list[dict[str, Any]] = field(default_factory=list)
    event_bus: EventBus = field(default_factory=lambda: EventBus(name="agent"))
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    # Unpruned tool pool (before agent-profile narrowing). Sub-agents must derive
    # their capabilities from here, otherwise the parent's deny list leaks into
    # every delegated agent. ``None`` means ``tool_registry`` is already complete.
    base_tool_registry: ToolRegistry | None = None
    iteration: int = 0
    max_iterations: int = 50
    model: str | None = None
    provider_name: str | None = None
    current_agent: str = "default"
    system_prompt: str | None = None
    locale: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)
    total_tokens: int = 0
    visible_tokens: int = 0
    approved_tools: set[str] = field(default_factory=set)
    tool_permissions: dict[str, str] = field(default_factory=dict)
    confirm_callback: Callable[..., Awaitable[bool]] | None = None
    ask_callback: Callable[..., Awaitable[str]] | None = None
    middlewares: MiddlewareChain | None = None

    # ── Interactive channel helpers ─────────────────────────────────────
    # Sub-agents inherit their parent's callbacks so permission prompts and
    # questions surface in the parent UI instead of being silently approved
    # (``confirm_callback is None`` means "no interactive channel → allow").
    # ``metadata["_agent_origin"]`` labels the prompt with the originating
    # sub-agent: {"agent_name", "display_name", "sub_agent_id"}.
    #
    # Callback arity is inspected statically (``inspect.signature``) rather
    # than probed by catching ``TypeError``: a ``TypeError`` raised *inside*
    # the callback would otherwise be mistaken for an arity mismatch and the
    # prompt would be re-issued. The serve callbacks accept an optional
    # ``origin`` trailing argument; the CLI callbacks predate it.

    @staticmethod
    def _max_positional(cb) -> int:
        try:
            sig = inspect.signature(cb)
        except (TypeError, ValueError):
            return 3
        count = 0
        for param in sig.parameters.values():
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
                count += 1
            elif param.kind is param.VAR_POSITIONAL:
                return 99
        return count

    async def confirm(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Ask the user to approve ``tool_name``. ``True`` when no channel exists."""
        cb = self.confirm_callback
        if cb is None:
            return True
        origin = self.metadata.get("_agent_origin")
        if origin and self._max_positional(cb) >= 3:
            return await cb(tool_name, args, origin)
        return await cb(tool_name, args)

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        multiple: bool = False,
        recommended: str | None = None,
        header: str | None = None,
    ) -> str:
        """Ask the user a question. Returns an error string when no channel exists."""
        cb = self.ask_callback
        if cb is None:
            return "Error: no ask callback available"
        origin = self.metadata.get("_agent_origin")
        arity = self._max_positional(cb)
        if arity >= 6:
            return await cb(question, options, multiple, recommended, header, origin)
        if arity >= 5:
            return await cb(question, options, multiple, recommended, header)
        return await cb(question, options, multiple)

    # Token accumulators (cumulative across all iterations in this run)
    accumulated_prompt: int = 0
    accumulated_completion: int = 0
    accumulated_cached: int = 0
    accumulated_reasoning: int = 0
    usage_records: list[dict[str, Any]] = field(default_factory=list)

    # ── Execution span collection (lightweight in-memory, flushed to DB after run) ──
    spans: list[dict[str, Any]] = field(default_factory=list)
    _span_counter: int = 0

    @property
    def accumulated_non_cached(self) -> int:
        return self.accumulated_prompt - self.accumulated_cached

    @property
    def accumulated_total(self) -> int:
        """Total billed tokens across every LLM call in this run."""
        return self.accumulated_prompt + self.accumulated_completion

    @property
    def accumulated_total_consumed(self) -> int:
        """Actual tokens consumed (non-cached input + all output)."""
        return self.accumulated_non_cached + self.accumulated_completion

    @property
    def budget_remaining(self) -> int:
        return max(0, self.max_iterations - self.iteration)

    @property
    def budget_exhausted(self) -> bool:
        return self.iteration >= self.max_iterations
