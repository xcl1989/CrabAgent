from __future__ import annotations

import asyncio
import json
import logging

from crabagent.core.database import async_session_factory
from crabagent.core.event import AgentEvent, EventType
from crabagent.serve.services.message import save_message

logger = logging.getLogger(__name__)


class PersistenceListener:
    def __init__(self, conversation_id: int, branch_id: str = "main"):
        self.conversation_id = conversation_id
        self.branch_id = branch_id
        self.sequence = 0
        self._buffer: list[dict] = []
        self._flush_task: asyncio.Task | None = None

    def _schedule_flush(self):
        if self._flush_task and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._flush())

    async def _flush(self):
        await asyncio.sleep(0.3)
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        try:
            async with async_session_factory() as db:
                for kwargs in batch:
                    await save_message(db, **kwargs)
        except Exception:
            logger.exception("Failed to flush %d messages (conv=%s)", len(batch), self.conversation_id)

    async def on_event(self, event: AgentEvent):
        if event.type != EventType.MESSAGE_CREATED:
            return

        msg = event.data.get("message")
        if not msg:
            return

        self.sequence += 1
        role = msg.get("role", "")
        content = msg.get("content") or ""
        tool_calls_raw = msg.get("tool_calls")
        tool_calls = json.dumps(tool_calls_raw) if tool_calls_raw else None
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")
        reasoning_content = msg.get("reasoning_content")

        self._buffer.append({
            "conversation_id": self.conversation_id,
            "sequence": self.sequence,
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "tool_call_id": tool_call_id,
            "name": name,
            "reasoning_content": reasoning_content,
            "branch_id": self.branch_id,
        })
        self._schedule_flush()

    async def finalize(self):
        if self._flush_task and not self._flush_task.done():
            await self._flush_task
        if self._buffer:
            await self._flush()
