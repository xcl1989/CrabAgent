"""Persisted user-turn memory batches and fail-closed transport admission."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from heapq import nsmallest

from sqlalchemy import func, select, text

from crabagent.core.config import settings
from crabagent.core.database import AgentMemory as Source
from crabagent.core.database import Conversation, Message, _memory_visible, async_session_factory
from crabagent.core.database import ConversationMemoryAnchor as Anchor
from crabagent.core.database import ConversationMemoryInjection as Snapshot

logger = logging.getLogger(__name__)
ANCHOR_ID = "_session_memory_anchor"
TURN_BUDGET = 6000
ITEM_BUDGET = 2400


# Chinese words that carry no topical signal; they match almost any request.
# With jieba segmentation these are whole words, so the list is small and
# stable (unlike the open-ended set of cross-word bigram fragments).
_STOP_BIGRAMS = frozenset(
    "一个 这个 那个 问题 需要 可以 应该 我们 你们 他们 一下 一些 什么 怎么 为什么 是否 不要 "
    "没有 就是 还是 但是 因为 所以 如果 然后 现在 之后 之前 时候 开始 进行 使用 提供 支持 实现 "
    "功能 内容 用户 消息 显示 前端 后端 修改 调整 处理 相关 部分 情况 方式 方法 配置 设置 "
    "一般 专门 操作 帮我 看看 有没 有没有 不好 不太 可能 太可 或者 来放 这边 那边 文件 东西 "
    "目前 已经 以及 方面 记录 数据 信息 结果 效果 质量 优化 方案 卡片 记忆 文档".split()
)
RESIDENT_BUDGET = 3000
# Resident ("always") entries are injected on *every* turn, so what matters is
# the cost of what gets injected, not the length of the stored text.  A long
# convention with a one-line ``summary`` is cheap to keep resident; the full
# text stays available through ``memory_recall``.  Entries without a summary
# must be short enough to inject verbatim.
RESIDENT_MAX_BYTES = 200
# Hard cap on resident entries per turn regardless of budget.  Without it a
# user with many conventions sees the same fixed block crowding out relevance.
RESIDENT_MAX_COUNT = 4
# ASCII terms shorter than this ("app", "the", "fix") are too weak to count.
_MIN_ASCII_TERM = 4
# A bigram present in at least this many visible memories is treated as
# generic ("可能", "文件", "文档") and cannot carry a hit on its own.  Derived
# from the corpus at rank time, so no hand-maintained stop list can fall
# behind the data.  An absolute count (not a ratio) is stable across corpus
# sizes: a topic word stays rare whether the user has 20 or 455 memories.
_GENERIC_DF_COUNT = 4
# Below this corpus size frequency counts are meaningless; fall back to the
# static stop list plus the original two-bigram minimum.
_MIN_CORPUS_FOR_IDF = 20


def _bigram_df(documents: list[set[str]]) -> dict[str, int]:
    """Return ``{bigram: number of documents containing it}``."""
    df: dict[str, int] = {}
    for terms in documents:
        for term in terms:
            df[term] = df.get(term, 0) + 1
    return df


def _is_generic(term: str, df_count: int | None) -> bool:
    """True when *term* is too weak to trigger a recall on its own.

    ``df_count`` is the number of visible memories containing *term*.
    ``None`` means corpus statistics are unavailable (tiny corpus), in which
    case only the static stop list applies and the caller additionally
    requires a second overlapping bigram.
    """
    if term in _STOP_BIGRAMS:
        return True
    if term.isascii():
        return len(term) < _MIN_ASCII_TERM
    # Unknown terms (df_count None) cannot be judged — keep them.
    return df_count is not None and df_count >= _GENERIC_DF_COUNT


def _is_resident(source) -> bool:
    """True for entries that qualify for every-turn injection."""
    return (source.recall_policy or "") == "always" and (
        source.memory_type == "team" or (source.memory_type == "user_preference" and source.source == "user")
    )


def _injectable(source) -> str:
    """Text actually injected for *source*: the summary when present, else content.

    Resident entries with a one-line summary stay cheap to inject every turn
    while the full text remains available through ``memory_recall``.
    """
    summary = (getattr(source, "summary", "") or "").strip()
    return summary if summary else (source.content or "")


def _candidate_rank(source, query: str, terms: set[str], corpus: dict[str, int] | None = None):
    """Rank *source* against *query*.

    ``corpus`` maps each bigram to the number of visible memories containing
    it.  ``None`` disables corpus statistics and falls back to the static
    stop list plus a two-bigram minimum — used for tiny corpora where
    frequency counts are meaningless.
    """
    key = (source.key or "").casefold()
    policy = source.recall_policy or ""
    fixed = policy == "always" and (
        source.memory_type == "team" or (source.memory_type == "user_preference" and source.source == "user")
    )
    if fixed and len(_injectable(source).encode("utf-8")) > RESIDENT_MAX_BYTES:
        # Demoted resident: still recallable, but must earn its place by relevance.
        fixed = False
    exact = len(key) >= 3 and bool(re.search(r"(?<![a-z0-9_])" + re.escape(key) + r"(?![a-z0-9_])", query))
    # Resident entries are scored for relevance too: when the user actually
    # asks about one, the full text is served instead of the digest.
    overlap = terms & _terms(f"{key} {source.content or ''}"[:4096]) if terms else set()
    counts = corpus or {}
    topical = {t for t in overlap if not _is_generic(t, counts.get(t))}
    # One *distinctive* bigram is enough when the rest of the query is generic
    # ("大屏在电视上" → 大屏).  Without corpus statistics a single bigram is
    # too weak, so require two — the original conservative rule.
    enough = bool(topical) and (corpus is not None or len(topical) >= 2)
    if not (fixed or exact or enough):
        return None
    strength = sum(1.0 / counts.get(t, 1) for t in topical)
    # Resident first (bounded), then exact key hits, then weighted overlap,
    # then workspace locality and importance.
    return (
        not fixed,
        not (exact or enough),
        not bool(source.workspace_path) if fixed else False,
        -strength,
        -bool(source.workspace_path),
        -(source.importance or 0),
        source.id,
    )


async def _vector_hits(visible, query: str, limit: int, excluded: set[str]) -> dict[str, float]:
    """Semantic recall over pre-computed embeddings → ``{memory_uid: similarity}``.

    Returns an empty mapping when the embedding model or vectors are
    unavailable so keyword ranking keeps working on its own.
    """
    from crabagent.core.database import agent_memory_vector_candidates

    try:
        rows = await agent_memory_vector_candidates(query, limit * 3, visible=visible)
    except Exception:
        logger.debug("vector recall unavailable", exc_info=True)
        return {}
    return {
        row["memory_uid"]: row["similarity"] for row in rows if row["memory_uid"] and row["memory_uid"] not in excluded
    }


def _terms(value: str) -> set[str]:
    """Tokenise *value* into matchable terms.

    Chinese is segmented with jieba so tokens are whole words ("大屏", "离屏",
    "渲染").  A sliding-window bigram over raw characters produced cross-word
    fragments ("个文", "建一", "能用") that matched almost anything; those are
    gone.  Words of 3+ characters also emit intra-word bigrams so a partial
    phrase still matches.  ASCII identifiers are kept whole.
    """
    import jieba

    terms: set[str] = set()
    for chunk in re.findall(r"[a-z0-9_]{3,}|[\u3400-\u9fff]+", value.casefold()):
        if chunk.isascii():
            terms.add(chunk)
            continue
        for word in jieba.lcut(chunk):
            word = word.strip()
            if len(word) < 2:
                continue
            terms.add(word)
            if len(word) >= 3:
                terms.update(word[i : i + 2] for i in range(len(word) - 1))
    return terms


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
        return (
            await db.execute(
                select(Snapshot, Source, Anchor)
                .join(Source, Source.memory_uid == Snapshot.memory_uid)
                .join(
                    Anchor,
                    (Anchor.anchor_message_id == Snapshot.anchor_message_id)
                    & (Anchor.conversation_id == Snapshot.conversation_id)
                    & (Anchor.branch_id == Snapshot.branch_id),
                )
                .join(Message, Message.id == Snapshot.anchor_message_id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    *self._branch(Snapshot),
                    *self._branch(Message),
                    Message.role == "user",
                    Message.compressed.is_(False),
                    Conversation.user_id == self.user_id,
                    Snapshot.anchor_message_id.in_(ids),
                    Snapshot.visibility_epoch == Source.visibility_epoch,
                    Snapshot.render_version == 1,
                    *self._visible(agent),
                )
                .order_by(Message.sequence, Message.id, Snapshot.ordinal, Snapshot.memory_uid)
            )
        ).all()

    async def _ranked(self, db, query, agent, excluded):
        limit = max(0, min(4, settings.memory_max_inject))
        if not limit:
            return []
        query = query[:2048].casefold()
        terms = _terms(query)
        stmt = select(Source).where(*self._visible(agent), Source.memory_uid.is_not(None))
        candidates = await db.stream_scalars(stmt.execution_options(yield_per=64))
        pool: dict[str, Source] = {}
        term_sets: dict[str, set[str]] = {}
        try:
            async for source in candidates:
                if not source.memory_uid:
                    continue
                pool[source.memory_uid] = source
                term_sets[source.memory_uid] = _terms(f"{source.key or ''} {source.content or ''}"[:4096])
        finally:
            await candidates.close()
        # Corpus-level document frequency: bigrams present in many memories
        # ("可能", "文件") are generic by construction and cannot carry a hit on
        # their own.  Too small a corpus makes counts meaningless, so the
        # static stop list plus the two-bigram minimum is used instead.
        corpus = _bigram_df(list(term_sets.values())) if len(term_sets) >= _MIN_CORPUS_FOR_IDF else None
        resident, ranked = [], []
        for uid, source in pool.items():
            if uid in excluded:
                continue
            rank = _candidate_rank(source, query, terms, corpus)
            if rank is None:
                continue
            if rank[0] == 0:  # resident
                resident.append((rank, source))
                # Also matched the query → eligible for full-text injection.
                if not rank[1]:
                    ranked.append((rank, source))
            else:
                ranked.append((rank, source))
        resident = nsmallest(limit, resident, key=lambda i: i[0])
        ranked = nsmallest(limit * 2, ranked, key=lambda i: i[0])
        # Fuse keyword hits with semantic hits (Reciprocal Rank Fusion) so a
        # memory surfaces when *either* signal is strong.  Keyword-only recall
        # misses paraphrases; vector-only recall misses exact identifiers.
        scores: dict[str, float] = {}
        for i, (rank, source) in enumerate(ranked):
            scores[source.memory_uid] = 1 / (60 + i)
        vector = await _vector_hits(self._visible(agent), query, limit, excluded)
        for i, (uid, similarity) in enumerate(sorted(vector.items(), key=lambda kv: kv[1], reverse=True)):
            source = pool.get(uid)
            if source is None or similarity < settings.memory_vector_threshold:
                continue
            scores[uid] = scores.get(uid, 0) + 1 / (60 + i)
        fused = sorted(
            (uid for uid in scores if uid in pool),
            key=lambda uid: (-scores[uid], uid),
        )
        relevance = [pool[uid] for uid in fused]
        relevant_uids = set(fused)
        # A resident entry that *also* matched the query is served in full via
        # the relevance channel — the user is asking about it, so the digest
        # alone would be a worse answer.
        resident = [(rank, s) for rank, s in resident if s.memory_uid not in relevant_uids]
        # Resident entries share a fixed cap (count *and* bytes, measured on what
        # is actually injected); relevance-ranked entries always keep at least
        # half of the slots and the rest of the byte budget.
        kept, cost = [], 0
        for rank, source in resident:
            payload_cost = len(_injectable(source).encode("utf-8")) + 80
            if cost + payload_cost > RESIDENT_BUDGET or len(kept) >= RESIDENT_MAX_COUNT:
                continue
            kept.append((rank, source))
            cost += payload_cost
        kept = kept[: max(1, limit // 2)]
        return [(s, True) for _, s in kept] + [(s, False) for s in relevance[: limit - len(kept)]]

    async def prepare(self, anchor_id: int, query: str, historical: set[int], agent: str) -> bool:
        try:
            async with async_session_factory() as db:
                rows = await self._batches(db, historical, agent) if historical else []
                active = [
                    snap
                    for snap, source, batch in rows
                    if snap.content_revision == source.content_revision
                    and (
                        snap.admitted or (not batch.first_admission_recorded and snap.anchor_message_id in self.pending)
                    )
                ]
                remaining = min(TURN_BUDGET, 20000 - sum(snap.token_count_estimate for snap in active))
                if remaining <= 0:
                    return False
                ranked = await self._ranked(db, query, agent, {snap.memory_uid for snap in active})
            selected = []
            for source, resident in ranked:
                payload = self._excerpt(source, min(ITEM_BUDGET, remaining), resident=resident)
                if payload is not None:
                    selected.append((source, payload))
                    remaining -= _cost(payload)
            if not selected:
                return False
            async with async_session_factory() as db:
                await db.execute(text("BEGIN IMMEDIATE"))
                anchor = await db.scalar(
                    select(Message.id)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Message.id == anchor_id,
                        *self._branch(Message),
                        Message.role == "user",
                        Message.compressed.is_(False),
                        Conversation.user_id == self.user_id,
                    )
                )
                if anchor is None or await db.get(Anchor, (self.conversation_id, self.branch_id, anchor_id)):
                    return False
                current = {
                    uid: (revision, epoch)
                    for uid, revision, epoch in await db.execute(
                        select(Source.memory_uid, Source.content_revision, Source.visibility_epoch).where(
                            *self._visible(agent), Source.memory_uid.in_([r.memory_uid for r, _ in selected])
                        )
                    )
                }
                selected = [
                    (r, value)
                    for r, value in selected
                    if current.get(r.memory_uid) == (r.content_revision, r.visibility_epoch)
                ]
                if not selected:
                    return False
                db.add(
                    Anchor(conversation_id=self.conversation_id, branch_id=self.branch_id, anchor_message_id=anchor_id)
                )
                for ordinal, (source, payload) in enumerate(selected):
                    db.add(
                        Snapshot(
                            conversation_id=self.conversation_id,
                            branch_id=self.branch_id,
                            anchor_message_id=anchor_id,
                            memory_uid=source.memory_uid,
                            content_revision=source.content_revision,
                            visibility_epoch=source.visibility_epoch,
                            ordinal=ordinal,
                            snapshot_payload=payload,
                            token_count_estimate=_cost(payload),
                        )
                    )
                await db.commit()
            self.pending.add(anchor_id)
            return True
        except Exception:
            logger.warning("Session memory preparation failed; using original turn", exc_info=True)
            return False

    @staticmethod
    def _payload(source, *, resident: bool = False):
        # Resident entries inject their summary (if any); relevance hits inject
        # the full text because the model asked for exactly this memory.
        body = _injectable(source) if resident else (source.content or "")
        data = {"id": source.memory_uid, "revision": source.content_revision, "key": source.key, "content": body}
        if resident and body != (source.content or ""):
            data["summary_of"] = True
        return _encoded(data)

    async def receipts(self, db, ids, agent):
        """Return visible, admitted titles without exposing the snapshot bodies.

        Each entry is ``{key, summary, memory_type, resident}`` so the UI can
        show *what* was injected (digest, type badge) instead of a bare key.
        Only the stored one-line ``summary`` is exposed — never the injected
        body, which may contain content the user did not ask to surface.
        """
        if not ids:
            return {}
        receipts: dict[int, list[dict]] = {}
        for snap, source, _ in await self._batches(db, ids, agent):
            if snap.admitted and snap.content_revision == source.content_revision:
                payload = json.loads(snap.snapshot_payload)
                key = payload.get("key")
                if not isinstance(key, str):
                    continue
                receipts.setdefault(snap.anchor_message_id, []).append(
                    {
                        "key": key,
                        "summary": (getattr(source, "summary", "") or "").strip(),
                        "memory_type": source.memory_type or "",
                        "resident": bool(payload.get("summary_of")),
                    }
                )
        return receipts

    @classmethod
    def _excerpt(cls, source, budget, *, resident: bool = False):
        payload = cls._payload(source, resident=resident)
        if _cost(payload) <= budget:
            return payload
        data = json.loads(payload)
        content = data.pop("content") or ""
        data["truncated"] = True
        low, high = 0, len(content)
        while low < high:
            mid = (low + high + 1) // 2
            if _cost(_encoded(dict(data, content=content[:mid]))) <= budget:
                low = mid
            else:
                high = mid - 1
        return _encoded(dict(data, content=content[:low])) if low else None

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
                    (snap, source)
                    for snap, source, _ in rows
                    if snap.content_revision == source.content_revision
                    and (snap.admitted or (snap.anchor_message_id in first and limit is None))
                    and (limit is None or (snap.anchor_message_id, snap.memory_uid) in limit)
                ]
                blocks = {}
                retry.allowed = set()
                for snap, _ in eligible:
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
