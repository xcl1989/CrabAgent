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

    async def persist_compression(self, summary: str, preserve_recent: int = 0) -> None:
        """Replace old context with a summary while retaining recent turns.

        Recent messages remain available to the next model call. Their sequence
        numbers are shifted to make the newly inserted summary sort immediately
        before them, even though its database id is newer.
        """
        await self.finalize()

        from sqlalchemy import func
        from sqlalchemy import select as sa_select
        from sqlalchemy import update as sa_update

        from crabagent.core.database import Message

        async with async_session_factory() as db:
            preserved_ids: list[int] = []
            summary_sequence: int
            if preserve_recent:
                preserved = await db.execute(
                    sa_select(Message)
                    .where(
                        Message.conversation_id == self.conversation_id,
                        Message.branch_id == self.branch_id,
                        Message.compressed == False,  # noqa: E712
                    )
                    .order_by(Message.sequence.desc(), Message.id.desc())
                    .limit(preserve_recent)
                )
                recent_messages = list(preserved.scalars().all())
                preserved_ids = [message.id for message in recent_messages]
                if recent_messages:
                    summary_sequence = min(message.sequence for message in recent_messages)
                    # Move retained turns after the summary without changing their order.
                    await db.execute(
                        sa_update(Message)
                        .where(Message.id.in_(preserved_ids))
                        .values(sequence=Message.sequence + 1)
                    )
                else:
                    summary_sequence = 1
            else:
                max_sequence = await db.scalar(
                    sa_select(func.max(Message.sequence)).where(
                        Message.conversation_id == self.conversation_id,
                        Message.branch_id == self.branch_id,
                    )
                )
                summary_sequence = (max_sequence or 0) + 1

            mark_old = (
                sa_update(Message)
                .where(
                    Message.conversation_id == self.conversation_id,
                    Message.branch_id == self.branch_id,
                    Message.compressed == False,  # noqa: E712
                )
            )
            if preserved_ids:
                mark_old = mark_old.where(Message.id.not_in(preserved_ids))
            await db.execute(mark_old.values(compressed=True))
            db.add(
                Message(
                    conversation_id=self.conversation_id,
                    sequence=summary_sequence,
                    role="compress",
                    content=summary,
                    branch_id=self.branch_id,
                    compressed=False,
                )
            )
            await db.commit()

        # Subsequent event-persisted messages must remain after retained turns.
        self.sequence = max(self.sequence, summary_sequence + preserve_recent)
        logger.info(
            "Persisted compression summary (%d chars) for conv=%s",
            len(summary), self.conversation_id,
        )
