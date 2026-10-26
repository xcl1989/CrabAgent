from __future__ import annotations

import asyncio
import logging

from crabagent.core.agent.context import AgentContext
from crabagent.core.database import token_usage_batch_create
from crabagent.core.event import AgentEvent, EventType

logger = logging.getLogger(__name__)


class UsagePersistenceListener:
    """Persist completed usage incrementally, retrying the unwritten tail on exit."""

    def __init__(self, context: AgentContext, user_id: int, session_id: str):
        self.context = context
        self.user_id = user_id
        self.session_id = session_id
        self.cursor = 0
        self._lock = asyncio.Lock()

    async def on_event(self, event: AgentEvent) -> None:
        if event.type in (EventType.ITERATION_END, EventType.SUB_AGENT_END):
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            records = self.context.usage_records[self.cursor :]
            if not records:
                return
            try:
                await token_usage_batch_create(
                    [
                        {
                            "user_id": self.user_id,
                            "session_id": self.session_id,
                            "agent_name": self.context.current_agent,
                            "model": self.context.metadata.get("resolved_model", self.context.model or ""),
                            "provider": self.context.metadata.get("resolved_provider", ""),
                            "branch_id": self.context.metadata.get("branch_id", "main"),
                            **record,
                        }
                        for record in records
                    ]
                )
                self.cursor += len(records)
            except Exception:
                logger.warning("Failed to persist token usage for %s", self.session_id, exc_info=True)
