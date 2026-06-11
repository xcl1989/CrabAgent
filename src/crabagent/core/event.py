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
    COMPRESS_START = "compress_start"
    COMPRESS_DELTA = "compress_delta"
    SCREENSHOT = "screenshot"
    SUB_AGENT_START = "sub_agent_start"
    SUB_AGENT_END = "sub_agent_end"
    SUB_AGENT_ERROR = "sub_agent_error"
    SUB_AGENT_TEXT_DELTA = "sub_agent_text_delta"
    SUB_AGENT_TOOL_CALL = "sub_agent_tool_call"
    SUB_AGENT_TOOL_RESULT = "sub_agent_tool_result"
    PIPELINE_START = "pipeline_start"
    PIPELINE_STEP_START = "pipeline_step_start"
    PIPELINE_STEP_END = "pipeline_step_end"
    PIPELINE_END = "pipeline_end"

    # Office document operations
    DOC_OP_START = "doc_op_start"
    DOC_OP_DELTA = "doc_op_delta"
    DOC_OP_PREVIEW = "doc_op_preview"
    DOC_OP_DONE = "doc_op_done"


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
    def __init__(self, name: str = ""):
        self._listeners: list = []
        self._name = name
        self._emit_count = 0
        self._emit_warn_threshold = 0.01

    def subscribe(self, callback) -> None:
        self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    async def emit(self, event: AgentEvent) -> None:
        import time as _t

        t0 = _t.monotonic()
        for callback in self._listeners:
            try:
                result = callback(event)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "[%s] emit listener %s raised on %s",
                    self._name,
                    getattr(callback, "__name__", callback),
                    event.type,
                    exc_info=True,
                )
        elapsed = _t.monotonic() - t0
        if elapsed > 0.2:
            import logging

            logging.getLogger(__name__).warning(
                "[%s] emit SLOW %.1fms listeners=%d event=%s",
                self._name,
                elapsed * 1000,
                len(self._listeners),
                event.type,
            )

    def emit_sync(self, event: AgentEvent) -> None:
        import logging
        import time

        self._emit_count += 1
        t0 = time.monotonic()
        for callback in self._listeners:
            try:
                callback(event)
            except Exception:
                logging.getLogger(__name__).warning(
                    "[%s] emit_sync listener %s raised on %s",
                    self._name,
                    getattr(callback, "__name__", callback),
                    event.type,
                    exc_info=True,
                )
        elapsed = time.monotonic() - t0
        if elapsed > self._emit_warn_threshold:
            logging.getLogger(__name__).warning(
                "[%s] emit_sync SLOW %.3fms listeners=%d event=%s (#%d)",
                self._name,
                elapsed * 1000,
                len(self._listeners),
                event.type,
                self._emit_count,
            )
