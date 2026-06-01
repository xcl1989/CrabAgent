from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crabagent.core.agent.tools.registry import ToolRegistry
from crabagent.core.event import EventBus


@dataclass
class AgentContext:
    workspace: Path
    messages: list[dict[str, Any]] = field(default_factory=list)
    event_bus: EventBus = field(default_factory=lambda: EventBus(name="agent"))
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    iteration: int = 0
    max_iterations: int = 50
    model: str | None = None
    provider_name: str | None = None
    current_agent: str = "default"
    system_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    total_tokens: int = 0
    approved_tools: set[str] = field(default_factory=set)
    confirm_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None
    ask_callback: Callable[[str, list[str] | None], Awaitable[str]] | None = None

    @property
    def budget_remaining(self) -> int:
        return max(0, self.max_iterations - self.iteration)

    @property
    def budget_exhausted(self) -> bool:
        return self.iteration >= self.max_iterations
