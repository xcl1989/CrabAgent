from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"
    ITERATION_START = "iteration_start"
    ITERATION_END = "iteration_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEXT_DELTA = "text_delta"
    TEXT_DONE = "text_done"
    THINKING_DELTA = "thinking_delta"
    THINKING_DONE = "thinking_done"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MESSAGE_CREATED = "message_created"
    TOOL_CONFIRM_REQUEST = "tool_confirm_request"
    USER_INPUT_REQUEST = "user_input_request"
    CONTEXT_COMPRESSED = "context_compressed"
    SCREENSHOT = "screenshot"


@dataclass
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


class EventBus:
    def __init__(self):
        self._listeners: list = []

    def subscribe(self, callback) -> None:
        self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    async def emit(self, event: AgentEvent) -> None:
        for callback in self._listeners:
            result = callback(event)
            if hasattr(result, "__await__"):
                await result

    def emit_sync(self, event: AgentEvent) -> None:
        for callback in self._listeners:
            callback(event)
