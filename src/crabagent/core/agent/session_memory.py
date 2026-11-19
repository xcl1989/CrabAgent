"""Persisted user-turn memory batches and fail-closed transport admission."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select, text

from crabagent.core.database import AgentMemory as Source
from crabagent.core.database import Conversation, Message, _memory_visible, async_session_factory
from crabagent.core.database import ConversationMemoryAnchor as Anchor
from crabagent.core.database import ConversationMemoryInjection as Snapshot

logger = logging.getLogger(__name__)
ANCHOR_ID = "_session_memory_anchor"


def _terms(value: str) -> set[str]:
    chunks = re.findall(r"[a-z0-9_]{3,}|[\u3400-\u9fff]+", value.casefold())
    return {
        term for chunk in chunks
        for term in ([chunk] if chunk.isascii() else [chunk[i:i + 2] for i in range(len(chunk) - 1)])
    }


def _encoded(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", r"\u003c").replace(">", r"\u003e")


def _cost(payload: str) -> int:
    return len(payload.encode("utf-8")) + 4


@dataclass
class SessionMemory:
    user_id: int
    conversation_id: int
    branch_id: str
    workspace: str
    pending: set[int] = field(default_factory=set)

    def _branch(self, model):
        return model.conversation_id == self.conversation_id, model.branch_id == self.branch_id

    def _visible(self, agent):
        return (
            Source.user_id == self.user_id,
            _memory_visible(self.workspace, agent),
            func.coalesce(Source.recall_policy, "").in_(("", "always", "query_only")),
        )

    async def _batches(self, db, ids, agent):
        return (await db.execute(
            select(Snapshot, Source, Anchor)
            .join(Source, Source.memory_uid == Snapshot.memory_uid)
            .join(Anchor, (Anchor.anchor_message_id == Snapshot.anchor_message_id) &
                  (Anchor.conversation_id == Snapshot.conversation_id) & (Anchor.branch_id == Snapshot.branch_id))
            .join(Message, Message.id == Snapshot.anchor_message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(*self._branch(Snapshot), *self._branch(Message), Message.role == "user",
                   Message.compressed.is_(False), Conversation.user_id == self.user_id,
                   Snapshot.anchor_message_id.in_(ids), Snapshot.visibility_epoch == Source.visibility_epoch,
                   Snapshot.render_version == 1, *self._visible(agent))
            .order_by(Message.sequence, Message.id, Snapshot.ordinal, Snapshot.memory_uid)
        )).all()

    async def prepare(self, anchor_id: int, query: str, historical: set[int], agent: str) -> None:
        try:
            async with async_session_factory() as db:
                await db.execute(text("BEGIN IMMEDIATE"))
                anchor = await db.scalar(
                    select(Message.id).join(Conversation, Conversation.id == Message.conversation_id).where(
                        Message.id == anchor_id, *self._branch(Message), Message.role == "user",
                        Message.compressed.is_(False), Conversation.user_id == self.user_id,
                    )
                )
                if anchor is None or await db.get(Anchor, (self.conversation_id, self.branch_id, anchor_id)):
                    return
                db.add(Anchor(conversation_id=self.conversation_id, branch_id=self.branch_id,
                              anchor_message_id=anchor_id))
                rows = await self._batches(db, historical, agent)
                active = {}
                total = 0
                for snap, source, batch in rows:
                    if snap.admitted or (not batch.first_admission_recorded and snap.anchor_message_id in self.pending
                                         and snap.content_revision == source.content_revision):
                        active[snap.memory_uid] = (snap, source)
                        total += snap.token_count_estimate
                selected = []
                for uid, (snap, source) in active.items():
                    if snap.content_revision == source.content_revision:
                        continue
                    payload = self._payload(source, snap.content_revision)
                    short = self._payload(source, snap.content_revision, short=True)
                    for candidate in (payload, short):
                        if _cost(candidate) <= 180 and total + _cost(candidate) <= 2000:
                            selected.append((source, candidate, snap.content_revision))
                            total += _cost(candidate)
                            break
                    else:
                        total -= sum(row.token_count_estimate for row, _, _ in rows
                                     if row.memory_uid == uid and row.admitted)
                query = query[:2048].casefold()
                terms = _terms(query)
                stmt = select(Source).where(*self._visible(agent), Source.memory_uid.is_not(None))
                candidates = await db.stream_scalars(
                    stmt.order_by(Source.importance.desc(), Source.id).execution_options(yield_per=64)
                )
                remaining = 400
                ordinary = 0
                async for source in candidates:
                    key = (source.key or "").casefold()
                    fixed = source.memory_type == "team" and source.recall_policy == "always"
                    exact = len(key) >= 3 and key in query
                    related = len(terms & _terms(f"{key} {source.content or ''}"[:4096])) >= 2
                    if source.memory_uid in active or not (fixed or exact or related):
                        continue
                    payload = self._payload(source)
                    cost = _cost(payload)
                    if cost <= min(180, remaining, 1500 - total):
                        selected.append((source, payload, None))
                        total += cost
                        remaining -= cost
                        ordinary += 1
                    if ordinary == 4:
                        break
                await candidates.close()
                for ordinal, (source, payload, supersedes) in enumerate(selected):
                    db.add(Snapshot(
                        conversation_id=self.conversation_id, branch_id=self.branch_id, anchor_message_id=anchor_id,
                        memory_uid=source.memory_uid, content_revision=source.content_revision,
                        visibility_epoch=source.visibility_epoch, ordinal=ordinal, snapshot_payload=payload,
                        token_count_estimate=_cost(payload), supersedes_revision=supersedes,
                    ))
                await db.commit()
            self.pending.add(anchor_id)
        except Exception:
            logger.warning("Session memory preparation failed; using original turn", exc_info=True)

    @staticmethod
    def _payload(source, previous=None, *, short=False):
        payload = {"id": source.memory_uid, "revision": source.content_revision}
        if previous is not None:
            payload["supersedes"] = previous
        if short:
            payload["note"] = "Do not rely on the old version. Consult the current record."
        else:
            payload.update(key=source.key, content=source.content)
        return _encoded(payload)

    async def complete(self, ids, agent, retry, build, send):
        """Check, record admission and enqueue under SQLite's writer lock."""
        limit = retry.allowed
        task = None
        try:
            async with async_session_factory() as db:
                await db.execute(text("BEGIN IMMEDIATE"))
                rows = await self._batches(db, ids, agent)
                fresh = self.pending & ids
                first = set()
                for anchor_id in fresh:
                    anchor = await db.get(Anchor, (self.conversation_id, self.branch_id, anchor_id))
                    if anchor and not anchor.first_admission_recorded:
                        anchor.first_admission_recorded = True
                        first.add(anchor_id)
                eligible = [
                    (snap, source) for snap, source, _ in rows
                    if (snap.admitted or (snap.anchor_message_id in first and limit is None
                                         and snap.content_revision == source.content_revision))
                    and (limit is None or (snap.anchor_message_id, snap.memory_uid) in limit)
                ]
                corrected = {snap.memory_uid for snap, source in eligible
                             if snap.content_revision == source.content_revision}
                blocks = {}
                retry.allowed = set()
                for snap, source in eligible:
                    if snap.content_revision != source.content_revision and snap.memory_uid not in corrected:
                        continue
                    if snap.anchor_message_id in first:
                        snap.admitted = True
                    retry.allowed.add((snap.anchor_message_id, snap.memory_uid))
                    blocks.setdefault(snap.anchor_message_id, []).append(snap.snapshot_payload)
                # Flush before enqueue: if the write fails, no snapshot is handed off.
                await db.flush()
                task = asyncio.create_task(send(build(blocks)))
                self.pending.difference_update(fresh)
                await db.commit()
        except asyncio.CancelledError:
            if task is not None:
                task.cancel()
            raise
        except Exception:
            if task is not None:
                return await task
            logger.warning("Session memory admission failed; sending without snapshots", exc_info=True)
            retry.allowed = set()
            self.pending.difference_update(ids)
            return await send(build({}))
        return await task


@dataclass
class Admission:
    allowed: set[tuple[int, str]] | None = None
