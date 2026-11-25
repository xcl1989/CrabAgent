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


async def test_always_policy_is_inert_unless_relevant(sessions, tmp_path):
    # ``recall_policy="always"`` used to inject these on *every* turn. It is now
    # inert: an unrelated turn gets nothing, a related turn recalls on demand.
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
    # Unrelated query: nothing at all.
    assert not await memory.prepare(1, "大屏一般在大电视上，不太可能用键盘打字操作", set(), "coder")
    # Related query: still recallable on demand.
    assert await memory.prepare(2, "非排他认领和文件协作怎么设计的", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {2}, "coder"))[2]]
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


async def test_summary_does_not_change_injection(sessions, tmp_path, monkeypatch):
    """``summary`` is a UI digest only; injection always uses the full content,
    truncated to the per-item budget. No resident digest channel exists."""
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
    # Unrelated query: nothing, summary or not.
    assert not await memory.prepare(1, "今天天气怎么样", set(), "coder")
    # Related query: full text, never the summary digest.
    assert await memory.prepare(2, "发布新版本到 PyPI 的流程", set(), "coder")
    records = [json.loads(item) for item in (await payload(memory, {2}, "coder"))[2]]
    hit = [r for r in records if r["key"] == "convention:release_pipeline_pypi"][0]
    assert "summary_of" not in hit
    assert "sync_version.py" in hit["content"]
    assert hit["content"] != "发版：改版本号→sync→README→push→build→twine upload"


async def test_always_entries_count_against_the_same_limit(sessions, tmp_path, monkeypatch):
    """``always`` entries take no reserved slots; relevance alone decides."""
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    for i in range(8):
        await add_source(sessions, f"rule-{i}", f"规则{i}", recall_policy="always", importance=0.9 - i * 0.01)
    await add_source(sessions, "backend", "修复 Python 后端后重启验证", importance=0.3)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "修复 Python 后端", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert keys == ["backend"]


async def test_long_always_without_summary_is_not_injected_when_unrelated(sessions, tmp_path):
    """No summary and too long → still nothing on an unrelated turn."""
    await add_source(sessions, "decision:long-note", "很长的决策说明。" * 60, recall_policy="always", importance=0.95)
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "今天天气怎么样", set(), "coder")


async def test_acknowledgement_only_turn_recalls_nothing(sessions, tmp_path):
    """A turn that is only an acknowledgement carries no topic to match."""
    await _seed_corpus(sessions)
    await add_source(sessions, "convention:cn_report", "问数模型工具约定：不要用 query_data_models")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "不用。", set(), "coder")
    assert not await memory.prepare(2, "好的", set(), "coder")


async def test_single_content_word_turn_recalls_nothing(sessions, tmp_path, monkeypatch):
    """A one-content-word turn must not pull anything in, resident or not.

    Production: "后续问题需要处理一下。" had one content word ("后续", not in the
    stop list at the time). Two ``always`` entries happened to contain it, were
    scored as *relevant*, and were injected in full — turning a topic-less turn
    into four injected memories. "后续" is now a stop word, and even if it were
    not, a single content word cannot pass the ``_MIN_QUERY_TERMS`` gate.
    """
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    await _seed_corpus(sessions)
    await add_source(
        sessions,
        "user_preference:collab_no_claim",
        "协作偏好：改完后让后续其他 Agent 知道文件被修改了什么",
        recall_policy="always",
        importance=0.5,
        summary="协作偏好：轻量变更可见性取代认领",
    )
    await add_source(
        sessions,
        "convention:unrelated_rule",
        "完全无关的项目约定",
        recall_policy="always",
        importance=0.9,
        summary="无关约定",
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "后续问题需要处理一下。", set(), "coder")
    # The same entry is still reachable when the query actually names it.
    assert await memory.prepare(2, "协作时不要显式认领文件锁", set(), "coder")


async def test_single_incidental_word_does_not_promote(sessions, tmp_path):
    """A multi-word query matching one incidental word must not recall.

    "electron" lives in packaging notes; a question about offscreen rendering
    must not pull the release pipeline in.
    """
    await _seed_corpus(sessions)
    await add_source(
        sessions,
        "convention:release_pipeline_pypi",
        "发版流程：同步两个 electron 目录的 package.json 后 build 并 twine upload",
        importance=0.9,
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "帮我看看 Electron 离屏渲染的截图怎么显示到界面上", set(), "coder")


async def test_subject_word_at_query_start_still_recalls(sessions, tmp_path):
    """The same rule must keep a genuine subject match: "大屏" leads the query."""
    await _seed_corpus(sessions)
    await add_source(sessions, "convention:dashboard_jump_id", "大屏跳转 ID 因租户而异，需向用户索取")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "大屏一般在大电视上，不太可能用键盘打字操作", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert keys == ["convention:dashboard_jump_id"]


async def test_two_word_query_single_hit_on_common_word_does_not_recall(sessions, tmp_path):
    """A two-word query matching one moderately common word must not recall.

    Production (2026-11-26): "已经看到窗口了" — the user meant the *app* window
    had appeared — recalled a preference about the model *context* window. The
    weak-single-word gate used to start at three content words, so a two-word
    query with one hit ("窗口", df=6) passed as a full match. The gate now
    applies from two words; a hit above ``_SINGLE_WORD_MAX_DF`` is rejected,
    while a rare hit still recalls.
    """
    await _seed_corpus(sessions, filler=100)
    # Push "窗口" past _SINGLE_WORD_MAX_DF (3) but keep it under the generic
    # threshold (int(105 * 0.06) = 6), as in production where six memories
    # mention a window of some kind.
    for i in range(4):
        await add_source(sessions, f"lesson:window_filler:{i}", f"第 {i} 条提到窗口的无关经验", importance=0.3)
    await add_source(
        sessions,
        "user_preference:new_model_context_limit",
        "新模型默认上下文 1,000,000 tokens；接口报告的窗口仍用于动态注册。",
        importance=0.8,
        summary="新模型默认上下文 1,000,000 tokens",
        workspace_path=str(tmp_path),
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    # Two content words ("界面", "窗口"); only "窗口" matches, and it is common.
    assert not await memory.prepare(1, "主界面窗口显示了", set(), "coder")
    # Naming the subject still recalls it.
    assert await memory.prepare(2, "新模型默认上下文窗口设多少", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {2}, "coder"))[2]]
    assert "user_preference:new_model_context_limit" in keys


async def test_two_word_query_single_rare_hit_still_recalls(sessions, tmp_path):
    """The two-word gate must not over-fire: one *rare* hit at the query start
    still recalls (same contract as the three-word case)."""
    await _seed_corpus(sessions)
    await add_source(sessions, "convention:dashboard_jump_id", "大屏跳转 ID 因租户而异，需向用户索取")
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "大屏在电视上", set(), "coder")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "coder"))[1]]
    assert keys == ["convention:dashboard_jump_id"]


async def test_other_workspace_memory_is_invisible(sessions, tmp_path):
    """A workspace-scoped memory never leaks into a different workspace.

    Cross-project leakage ("大屏" pulling in a wolfkill speech note) comes from
    memories that were *stored* as global; visibility itself is enforced by the
    SQL scope filter, so a workspace-scoped row is not even a candidate here.
    """
    await _seed_corpus(sessions)
    other = str(tmp_path / "other-project")
    await add_source(
        sessions,
        "architecture:speech-pipeline",
        "wolfkill 发言流水线：文字与语音合并广播，含打字与键盘输入处理",
        scope="workspace",
        workspace_path=other,
    )
    memory = sm.SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "大屏一般在大电视上，不太可能用键盘打字操作", set(), "coder")
    assert not await memory.prepare(2, "wolfkill 发言流水线怎么合并语音广播", set(), "coder")
    # The same memory is visible from its own workspace.
    home = sm.SessionMemory(7, 1, "main", other)
    assert await home.prepare(3, "wolfkill 发言流水线怎么合并语音广播", set(), "coder")
