"""Regression tests for auto-recall quality (P0/P1 of the recall optimisation).

Covers the three failures observed in production:

1. Long ``always`` project decisions were injected on *every* turn and crowded
   the prompt with the same fixed block.
2. Chinese bigram matching had no discriminative power: "文档" / "方案" alone
   dragged unrelated memories in, while a genuinely distinctive term with a
   single bigram ("大屏") was dropped by the ``>= 2`` rule.
3. Semantic recall was never wired into auto-injection, so paraphrases never
   matched.
"""

import json

from crabagent.core import database
from crabagent.core.agent import loop
from crabagent.core.agent import session_memory as sm
from tests.test_session_memory_guard import add_source, payload


async def test_long_always_entries_are_demoted_from_resident_pool(sessions, tmp_path):
    # A 2000-char "always" decision used to take a resident slot on every turn.
    await add_source(
        sessions,
        "decision:nonexclusive_file_collaboration",
        "CrabAgent 项目协作里的认领是非排他的编辑意向。" * 80,
        recall_policy="always",
        importance=0.92,
    )
    await add_source(
        sessions,
        "convention:release_pipeline_pypi",
        "版本源 pyproject.toml → sync_version.py",
        recall_policy="always",
        importance=0.7,
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    # Unrelated query: only the concise resident stays; the long one must not.
    assert await memory.prepare(1, "大屏一般在大电视上，不太可能用键盘打字操作", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert "convention:release_pipeline_pypi" in keys
    assert "decision:nonexclusive_file_collaboration" not in keys
    # Related query: the demoted entry is still recallable on demand.
    assert await memory.prepare(2, "非排他认领和文件协作怎么设计的", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1, 2}, "coder"))[2]]
    assert "decision:nonexclusive_file_collaboration" in keys


async def _seed_corpus(sessions, filler: int = 25):
    """Add enough unrelated memories for corpus statistics to kick in.

    Production has hundreds of memories; with fewer than
    ``_MIN_CORPUS_FOR_IDF`` the ranker deliberately falls back to the static
    stop list, which is a different code path.
    """
    for i in range(filler):
        await add_source(sessions, f"lesson:filler:{i}", f"filler lesson {i} about topic{i % 7}", importance=0.3)


async def test_generic_nouns_alone_do_not_recall(sessions, tmp_path):
    # "文档" matched a MiniMax note purely by accident in production: it is a
    # generic noun that appears across many memories and must not carry a hit.
    await _seed_corpus(sessions)
    for i in range(6):
        await add_source(sessions, f"note:docs:{i}", "文档说明和记录整理")
    await add_source(
        sessions,
        "project:minimax-h3-selfhost",
        "用户正在本机 M3 16GB MacBook Pro 上通过 VPIPE 自部署 MiniMax H3 视频生成模型。关键事实：安装 vpipe、"
        "下载权重、文档说明。",
    )
    await add_source(sessions, "lesson:hunter-llm-shot", "狼人杀猎人开枪由 LLM 决策，失败回退随机方案。")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "这这边建一个文件夹，来放文档和原型。", set(), "coder")
    # A distinctive term must still reach the right memory.
    assert await memory.prepare(2, "VPipe 本地部署 MiniMax 视频模型怎么装", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1, 2}, "coder"))[2]]
    assert keys == ["project:minimax-h3-selfhost"]


async def test_single_distinctive_bigram_is_enough(sessions, tmp_path):
    # "大屏" is distinctive; the old ">= 2 overlapping bigrams" rule dropped it.
    await _seed_corpus(sessions)
    await add_source(
        sessions,
        "convention:dashboard_jump_id",
        "大屏跳转 ID 因租户而异，不存在通用 ID，需向用户索取。",
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "大屏一般在大电视上，不太可能用键盘打字操作", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert keys == ["convention:dashboard_jump_id"]


async def test_vector_hits_are_fused_with_keyword_hits(sessions, tmp_path, monkeypatch):
    # No lexical overlap at all; only an embedding can connect these.
    await add_source(sessions, "lesson:electron-offscreen", "离屏渲染可截图但无法直接挂到可见窗口显示")
    calls = []

    async def fake_candidates(query, limit, *, visible=None):
        calls.append(query)
        return [{"memory_uid": uid, "key": "lesson:electron-offscreen", "similarity": 0.81} for uid in visible_uids]

    async with sessions() as db:
        visible_uids = [
            r.memory_uid
            for r in (
                await db.execute(
                    __import__("sqlalchemy")
                    .select(database.AgentMemory)
                    .where(database.AgentMemory.key == "lesson:electron-offscreen")
                )
            ).scalars()
        ]
    monkeypatch.setattr(database, "agent_memory_vector_candidates", fake_candidates)
    monkeypatch.setattr(loop.settings, "memory_vector_threshold", 0.45)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "后台 BrowserWindow 截图怎么显示到界面上", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert keys == ["lesson:electron-offscreen"]
    assert calls and "后台" in calls[0]


async def test_vector_hits_below_threshold_are_ignored(sessions, tmp_path, monkeypatch):
    await add_source(sessions, "lesson:electron-offscreen", "离屏渲染可截图但无法直接挂到可见窗口显示")
    async with sessions() as db:
        uid = (
            (
                await db.execute(
                    __import__("sqlalchemy")
                    .select(database.AgentMemory)
                    .where(database.AgentMemory.key == "lesson:electron-offscreen")
                )
            )
            .scalar_one()
            .memory_uid
        )

    async def weak(query, limit, *, visible=None):
        return [{"memory_uid": uid, "key": "lesson:electron-offscreen", "similarity": 0.2}]

    monkeypatch.setattr(database, "agent_memory_vector_candidates", weak)
    monkeypatch.setattr(loop.settings, "memory_vector_threshold", 0.45)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "今天天气怎么样", set(), "coder")


async def test_backfill_embeddings_is_idempotent(sessions, tmp_path, monkeypatch):
    from crabagent.core import memory_embed

    await add_source(sessions, "a", "first")
    await add_source(sessions, "b", "second")
    encoded = []

    async def fake_encode(text):
        encoded.append(text)
        return b"\x00" * 4

    monkeypatch.setattr(memory_embed, "encode", fake_encode)
    from sqlalchemy import func, select

    async with sessions() as db:
        monkeypatch.setattr(database, "async_session_factory", sessions)
    assert await database.agent_memory_backfill_embeddings(7) == 2
    assert await database.agent_memory_backfill_embeddings(7) == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(database.MemoryEmbedding)) == 2
    assert sorted(encoded) == ["a: first", "b: second"]


async def test_summary_keeps_long_convention_resident(sessions, tmp_path, monkeypatch):
    """A long convention with a one-line summary stays resident; the model sees
    the digest and can pull the full text via memory_recall."""
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    body = (
        "发布流程：版本源 pyproject.toml → sync_version.py → 更新 README → git push → build → twine upload 到 PyPI。"
        * 12
    )
    await add_source(
        sessions,
        "convention:release_pipeline_pypi",
        body,
        recall_policy="always",
        importance=0.7,
        summary="发版：改版本号→sync→README→push→build→twine upload",
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    # Unrelated query: still resident, and only the digest is injected.
    assert await memory.prepare(1, "今天天气怎么样", set(), "coder")
    raw = (await payload(memory, {1}, "coder"))[1]
    records = list(map(json.loads, raw))
    assert [r["key"] for r in records] == ["convention:release_pipeline_pypi"]
    assert records[0]["summary_of"] is True
    assert "sync" in records[0]["content"] and len(records[0]["content"]) < 80
    # Related query: the full text is injected because relevance asked for it.
    assert await memory.prepare(2, "发布新版本到 PyPI 的流程", set(), "coder")
    full = [json.loads(item) for item in (await payload(memory, {1, 2}, "coder"))[2]]
    assert "summary_of" not in [r for r in full if r["key"] == "convention:release_pipeline_pypi"][0]


async def test_resident_pool_is_hard_capped(sessions, tmp_path, monkeypatch):
    """Many short conventions must not crowd out relevance-ranked memories."""
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    for i in range(8):
        await add_source(sessions, f"rule-{i}", f"规则{i}", recall_policy="always", importance=0.9 - i * 0.01)
    await add_source(sessions, "backend", "修复 Python 后端后重启验证", importance=0.3)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "修复 Python 后端", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert "backend" in keys
    assert sum(k.startswith("rule-") for k in keys) <= sm.RESIDENT_MAX_COUNT


async def test_long_resident_without_summary_is_demoted(sessions, tmp_path):
    """No summary and too long → on-demand only, so it cannot dominate the prompt."""
    await add_source(sessions, "decision:long-note", "很长的决策说明。" * 60, recall_policy="always", importance=0.95)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "今天天气怎么样", set(), "coder")
