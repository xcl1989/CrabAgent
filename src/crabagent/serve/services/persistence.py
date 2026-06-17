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
        saved_ids: list[tuple[int, str]] = []
        try:
            async with async_session_factory() as db:
                for kwargs in batch:
                    msg = await save_message(db, **kwargs)
                    content = kwargs.get("content", "")
                    role = kwargs.get("role", "")
                    if content and role in ("assistant", "user"):
                        saved_ids.append((msg.id, content))
        except Exception:
            logger.exception("Failed to flush %d messages (conv=%s)", len(batch), self.conversation_id)

        # Index after session closed to avoid SQLite lock conflicts
        if saved_ids:
            try:
                from crabagent.core.fts import index_message
                for mid, content in saved_ids:
                    await index_message(mid, content)
            except Exception:
                logger.debug("[FTS] Index batch failed (non-fatal)")

    async def on_event(self, event: AgentEvent):
        if event.type != EventType.MESSAGE_CREATED:
            return

        msg = event.data.get("message")
        if not msg:
            return

        self.sequence += 1
        role = msg.get("role", "")
        raw_content = msg.get("content")
        # v0.9 — tool results may be list[dict] (multimodal: text + image_url).
        # Persist as JSON string; message_to_dict will deserialize on read.
        if isinstance(raw_content, list):
            content = json.dumps(raw_content, ensure_ascii=False)
        elif raw_content is None:
            content = ""
        else:
            content = raw_content
        tool_calls_raw = msg.get("tool_calls")
        tool_calls = json.dumps(tool_calls_raw) if tool_calls_raw else None
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")
        reasoning_content = msg.get("reasoning_content")

        self._buffer.append(
            {
                "conversation_id": self.conversation_id,
                "sequence": self.sequence,
                "role": role,
                "content": content,
                "tool_calls": tool_calls,
                "tool_call_id": tool_call_id,
                "name": name,
                "reasoning_content": reasoning_content,
                "branch_id": self.branch_id,
                "agent": msg.get("agent", "default"),
            }
        )
        self._schedule_flush()

    async def finalize(self):
        if self._flush_task and not self._flush_task.done():
            await self._flush_task
        if self._buffer:
            await self._flush()

    async def persist_compression(self, summary: str) -> None:
        """Mark all existing messages as compressed and insert the summary.

        Called inline when context compression occurs (from compress.py).
        After this, new messages saved by PersistenceListener (the current
        iteration's assistant/tool responses) will have higher ids,
        naturally appearing after the summary in the database.

        Flow:
          1. Flush pending buffered saves (previous iterations' messages)
          2. Mark ALL existing non-compressed messages as compressed=True
          3. Insert the summary as the sole non-compressed message
        """
        # 1. Flush pending buffered saves first
        await self.finalize()

        from sqlalchemy import update as sa_update

        from crabagent.core.database import Message

        # 2. Mark ALL existing messages as compressed
        async with async_session_factory() as db:
            await db.execute(
                sa_update(Message)
                .where(
                    Message.conversation_id == self.conversation_id,
                    Message.branch_id == self.branch_id,
                    Message.compressed == False,  # noqa: E712
                )
                .values(compressed=True)
            )
            # 3. Insert summary as the only non-compressed message
            db.add(
                Message(
                    conversation_id=self.conversation_id,
                    sequence=0,
                    role="compress",
                    content=summary,
                    branch_id=self.branch_id,
                    compressed=False,
                )
            )
            await db.commit()
        logger.info(
            "Persisted compression summary (%d chars) for conv=%s",
            len(summary), self.conversation_id,
        )
