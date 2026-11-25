"""Persisted user-turn memory batches and fail-closed transport admission."""

from __future__ import annotations

import asyncio
import json
import logging
import math
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
    # Conversational acknowledgements / backchannels. A turn that is only one
    # of these ("不用。", "好的", "行") carries no topic at all.
    + "不用 好的 行吧 好吧 可以 那行 没问题 谢谢 继续 知道 明白 懂了 嗯哦 好嘞 不用了 "
    "等等 等一下 等下 慢着 停 一下 先不 先不用 算了 还是 吧 呢 啊 哦 嗯 好的呀".split()
    # Temporal / sequencing words. "后续" matched two unrelated memories in
    # production on the turn "后续问题需要处理一下。" and pulled them in.
    + "后续 接着 随后 后面 前面 刚才 刚刚 接下来 以后 从此 自此 当时 原来 本来 之后 之前".split()
    # Perception verbs name an action, never a subject. "已经看到窗口了" (the
    # app window appeared) matched a memory about "seeing" thinking blocks in
    # the frontend; the verb carried the hit on its own.
    + "看到 看见 听到 收到 发现 找到 打开 点开 试过 试了 用过 碰到 遇到 碰见".split()
)
# ASCII terms shorter than this ("app", "the", "fix") are too weak to count.
_MIN_ASCII_TERM = 4
# A word present in at least this *share* of the visible memories is treated as
# generic ("可能", "文件") and cannot carry a hit on its own. Derived from the
# corpus at rank time, so no hand-maintained stop list can fall behind the data.
# A ratio rather than an absolute count: with 260 memories a word seen 8 times
# is a real topic ("发布" in a project that ships weekly), while at 20 memories
# 8 occurrences would be a third of everything.
_GENERIC_DF_RATIO = 0.06
# Floor and ceiling so the ratio stays sane for very small and very large
# corpora (20 memories → 2; 500 → 30).
_GENERIC_DF_MIN = 3
_GENERIC_DF_MAX = 40
# Below this corpus size frequency counts are meaningless; fall back to the
# static stop list plus the original two-bigram minimum.
_MIN_CORPUS_FOR_IDF = 20
# A query with fewer content words than this is treated as carrying no topic
# for keyword matching ("不用。", "好的").  Vector recall still applies.
_MIN_QUERY_TERMS = 2
# Tool, library and platform names are never a *subject*: "electron" shows up
# in packaging notes, release logs and UI work alike, so a single match on one
# of these says nothing about what the user is asking. They may still
# contribute when accompanied by other matched words.
_TECH_TERMS = frozenset(
    "electron python node react vue typescript javascript fastapi flask django sqlalchemy "
    "docker git github npm pip pnpm yarn vite webpack pytest asyncio sqlite postgres mysql "
    "redis linux macos windows ubuntu tailwind html css json yaml toml markdown "
    "openai anthropic claude gpt litellm langchain pydantic uvicorn "
    "officecli excel word powerpoint docx xlsx pptx".split()
)
# When a multi-word query matches a memory on exactly one word, that word must
# be rare enough to name the subject rather than a tool or library everyone
# mentions, and it must sit early in the query where Chinese puts the subject.
_SINGLE_WORD_MAX_DF = 3
_SINGLE_WORD_MIN_SHARE = 0.3
# A memory recorded in a *different* workspace must reach this IDF-weighted
# coverage before it may be recalled into the current one. Cross-project
# leakage ("大屏" pulling in a wolfkill speech note) is worse than a miss.
_CROSS_WORKSPACE_MIN_COVERAGE = 0.5


def _bigram_df(documents: list[set[str]]) -> dict[str, int]:
    """Return ``{bigram: number of documents containing it}``."""
    df: dict[str, int] = {}
    for terms in documents:
        for term in terms:
            df[term] = df.get(term, 0) + 1
    return df


def _generic_threshold(corpus_size: int) -> int:
    """Document frequency at or above which a word is considered generic.

    Scales with the corpus so that "发布" (df=8) stays a topic in a 260-memory
    project while still being generic in a 40-memory one.
    """
    return max(_GENERIC_DF_MIN, min(_GENERIC_DF_MAX, int(corpus_size * _GENERIC_DF_RATIO)))


def _is_generic(term: str, df_count: int | None, corpus_size: int = 0) -> bool:
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
    return df_count is not None and df_count >= _generic_threshold(corpus_size)


def _query_word_order(value: str) -> list[str]:
    """Content words of *value* in their original order (stop words removed).

    Position matters: the subject of a Chinese question usually comes first,
    so a memory matching the leading word is a stronger candidate than one
    matching a trailing detail.
    """
    import jieba

    ordered: list[str] = []
    for chunk in re.findall(r"[a-z0-9_]{3,}|[\u3400-\u9fff]+", value.casefold()):
        if chunk.isascii():
            if len(chunk) >= _MIN_ASCII_TERM and chunk not in _STOP_BIGRAMS:
                ordered.append(chunk)
            continue
        for word in jieba.lcut(chunk):
            word = word.strip()
            if len(word) >= 2 and word not in _STOP_BIGRAMS:
                ordered.append(word)
    return ordered


def _candidate_rank(
    source,
    query: str,
    terms: set[str],
    corpus: dict[str, int] | None = None,
    query_terms: set[str] | None = None,
    corpus_size_hint: int = 0,
    workspace_hint: str = "",
):
    """Rank *source* against *query*.

    ``corpus`` maps each bigram to the number of visible memories containing
    it.  ``None`` disables corpus statistics and falls back to the static
    stop list plus a two-bigram minimum — used for tiny corpora where
    frequency counts are meaningless.  ``query_terms`` are the query's content
    words (stop words removed); when the whole query has fewer than
    ``_MIN_QUERY_TERMS`` of them, keyword recall is skipped entirely.
    """
    key = (source.key or "").casefold()
    exact = len(key) >= 3 and bool(re.search(r"(?<![a-z0-9_])" + re.escape(key) + r"(?![a-z0-9_])", query))
    overlap = terms & _terms(f"{key} {source.content or ''}"[:4096]) if terms else set()
    counts = corpus or {}
    topical = {t for t in overlap if not _is_generic(t, counts.get(t), corpus_size_hint)}
    # A query that has fewer than two content words carries almost no signal:
    # "不用。" matching a memory that also says "不用" is 100% lexical overlap
    # and zero meaning.  Leave such turns to the semantic channel instead of
    # letting a single shared word pull an unrelated memory in.
    if len(query_terms or ()) < _MIN_QUERY_TERMS and not exact:
        return None
    # One *distinctive* bigram is enough when the rest of the query is generic
    # ("大屏在电视上" → 大屏).  Without corpus statistics a single bigram is
    # too weak, so require two — the original conservative rule.
    enough = bool(topical) and (corpus is not None or len(topical) >= 2)
    if not (exact or enough):
        return None
    # A single matched word out of a multi-word query is weak evidence: the
    # memory merely mentions the word. Two signals decide whether it is still
    # worth recalling, and both must hold:
    #   * the word must be *specific* — "electron" is a tool name, while
    #     "大屏" names the subject;
    #   * it must sit early in the query, where Chinese puts the subject.
    # Position alone let "electron" (first content word of "帮我看看 Electron
    # 离屏渲染…") drag a release note into an offscreen-rendering question.
    # The gate applies to two-word queries too: "已经看到窗口了" (the app
    # window) recalled six memories about the *context* window because "窗口"
    # alone counted as a full hit; with df=6 it is now rejected as too common.
    if len(topical) == 1 and len(query_terms or ()) >= 2 and not exact:
        hit = next(iter(topical))
        order = [t for t in _query_word_order(query) if t in query_terms]
        pos = order.index(hit) if hit in order else len(order)
        # First word → 1.0, second → 0.59, third → 0.43, …
        total = sum(1.0 / (1.0 + 0.7 * i) for i in range(len(order))) or 1.0
        share = (1.0 / (1.0 + 0.7 * pos)) / total
        if hit in _TECH_TERMS or counts.get(hit, 0) > _SINGLE_WORD_MAX_DF or share < _SINGLE_WORD_MIN_SHARE:
            # A single incidental word is not a reason to inject.
            return None

    # Coverage first, rarity second — but coverage is IDF-weighted so that
    # matching "大屏" (the subject) counts for more than matching an incidental
    # "打字". Comparing the matched weight against the query's *total* weight
    # keeps the score in [0, 1] and independent of how many words the query has.
    #
    # BM25-style IDF rather than a bare 1/df: a word absent from the corpus
    # ("键盘", df=0) must not out-score a rare-but-present subject word
    # ("大屏", df=2). 1/df gave OOV terms the maximum weight, letting any
    # memory containing an incidental rare word beat the one matching the topic.
    corpus_size = corpus_size_hint or 1

    def _w(t: str) -> float:
        d = counts.get(t, 0)
        return math.log(1.0 + (corpus_size - d + 0.5) / (d + 0.5))

    total_weight = sum(_w(t) for t in (query_terms or ())) or 1.0
    coverage = sum(_w(t) for t in topical) / total_weight
    strength = sum(_w(t) for t in topical)
    # Workspace affinity. A global-scope memory is visible from every
    # workspace, so a wolfkill speech-pipeline note competes with a CrabAgent
    # question on equal footing. Memories recorded in the current workspace
    # rank above global ones, and a *different* workspace's memory must earn a
    # clearly stronger match before it is allowed in at all.
    local = bool(source.workspace_path) and source.workspace_path == (workspace_hint or "")
    other_workspace = bool(source.workspace_path) and bool(workspace_hint) and source.workspace_path != workspace_hint
    if other_workspace and not exact and coverage < _CROSS_WORKSPACE_MIN_COVERAGE:
        return None
    # Relevance (exact key beats topical overlap), then workspace affinity,
    # coverage, strength, importance.
    return (
        not exact,
        not local,
        -coverage,
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
        # Content words only: a turn made purely of acknowledgements ("不用。")
        # has no topic to match on.
        query_terms = terms - _STOP_BIGRAMS
        ranked = []
        for uid, source in pool.items():
            if uid in excluded:
                continue
            rank = _candidate_rank(source, query, terms, corpus, query_terms, len(pool), self.workspace)
            if rank is None:
                continue
            ranked.append((rank, source))
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
        return [pool[uid] for uid in fused[:limit]]

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
            for source in ranked:
                payload = self._excerpt(source, min(ITEM_BUDGET, remaining))
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
    def _payload(source):
        data = {
            "id": source.memory_uid,
            "revision": source.content_revision,
            "key": source.key,
            "content": source.content or "",
        }
        return _encoded(data)

    async def receipts(self, db, ids, agent):
        """Return visible, admitted titles without exposing the snapshot bodies.

        Each entry is ``{key, summary, memory_type}`` so the UI can show *what*
        was injected (digest, type badge) instead of a bare key.  Only the
        stored one-line ``summary`` is exposed — never the injected body, which
        may contain content the user did not ask to surface.
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
                    }
                )
        return receipts

    @classmethod
    def _excerpt(cls, source, budget):
        payload = cls._payload(source)
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
