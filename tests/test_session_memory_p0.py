import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update

from crabagent.core import database, proxy
from crabagent.core.agent import loop
from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.session_memory import ANCHOR_ID, Admission, SessionMemory, Source
from crabagent.core.event import EventType
from crabagent.serve.api.message import list_messages
from tests.test_session_memory_guard import add_source, payload


@pytest.mark.parametrize("provider_type", ["openai", "zhipu"])
async def test_replays_identical_prefix_after_reload(sessions, tmp_path, monkeypatch, provider_type):
    await add_source(sessions, "backend", "After fixing the Python backend, restart and verify.")
    await add_source(sessions, "install", "Test after installing the desktop app.", importance=1)
    await add_source(sessions, "hidden", "Fix the Python backend.", scope="workspace", workspace_path="/other")
    monkeypatch.setattr(loop.settings, "session_memory_models", [])
    monkeypatch.setattr(proxy, "resolve_llm_proxy", AsyncMock(return_value=""))
    monkeypatch.setattr(loop, "_get_default_model_settings", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(
        loop,
        "_resolve_provider",
        AsyncMock(
            return_value=SimpleNamespace(
                name="test",
                provider_type=provider_type,
                api_key="test",
                base_url="",
            )
        ),
    )
    sent = []
    events = []

    async def completion(**params):
        sent.append(params["messages"])

        async def stream():
            delta = SimpleNamespace(content="ok", tool_calls=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")])

        return stream()

    monkeypatch.setattr(loop.litellm, "acompletion", completion)
    for anchor, query in [(1, "Fix the Python backend"), (2, "What is the weather?")]:
        context = AgentContext(workspace=tmp_path, model="gpt-4o", current_agent="coder")
        if anchor == 2:
            context.messages.extend(
                [
                    {"role": "user", "content": "Fix the Python backend", ANCHOR_ID: 1},
                    {"role": "assistant", "content": "ok"},
                ]
            )
        context.event_bus.subscribe(events.append)
        context.metadata.update(
            _session_memory=SessionMemory(7, 1, "main", str(tmp_path)), _initial_memory_anchor=anchor
        )
        await loop.run_agent(context, query)
        assert all("session-memory-reference>" not in str(message) for message in context.messages)

    assert "restart and verify" in json.dumps(sent[0])
    assert "desktop app" not in json.dumps(sent)
    assert '"hidden"' not in json.dumps(sent)
    assert sent[1][: len(sent[0])] == sent[0]
    assert "session-memory-reference>" not in sent[1][-1]["content"]
    assert [event.data for event in events if event.type == EventType.MEMORY_REFERENCES] == [
        {"anchor_id": 1, "keys": ["backend"]},
    ]


async def test_hits_rank_by_priority_and_relevance_allow_cjk_and_respect_budget(
    sessions,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    await add_source(sessions, "global-rule", "Global default", recall_policy="always", importance=1)
    await add_source(
        sessions,
        "workspace-rule",
        "Workspace wins",
        recall_policy="always",
        scope="workspace",
        workspace_path=str(tmp_path),
        importance=0.1,
    )
    await add_source(
        sessions,
        "python-backend",
        "修复 Python 后端后，重启相关进程再验证。" * 1200,
        scope="agent",
        agent_name="coder",
        workspace_path=str(tmp_path),
    )
    await add_source(sessions, "manual", "修复 Python 后端", recall_policy="manual")
    await add_source(
        sessions, "other-agent", "修复 Python 后端", scope="agent", agent_name="reviewer", workspace_path=str(tmp_path)
    )
    memory = SessionMemory(7, 1, "main", str(tmp_path))
    await memory.prepare(1, "请修复 Python 后端", set(), "coder")
    raw = (await payload(memory, {1}, "coder"))[1]
    records = list(map(json.loads, raw))
    # Resident entries take at most half the slots; the relevance hit gets one.
    assert [record["key"] for record in records] == ["workspace-rule", "global-rule", "python-backend"]
    assert records[-1]["truncated"] is True
    assert all(len(item.encode()) + 4 <= 2400 for item in raw)


async def test_generic_bigrams_do_not_recall_topic_knowledge(sessions, tmp_path):
    # Mirrors a real miss: a WeChat feature note matched "前端/显示/消息" only.
    await add_source(
        sessions,
        "feature:wechat",
        "微信 iLink Bot 集成已实现：扫码登录、Long-Poll 消息接收、Agent 处理。前端显示消息卡片，core/wechat/client.py",
    )
    memory = SessionMemory(7, 1, "main", str(tmp_path))
    assert not await memory.prepare(1, "前端的显示中，记忆的卡片把消息切开了", set(), "default")
    assert await memory.prepare(2, "微信扫码登录怎么实现", set(), "default")


async def test_resident_pool_is_capped_and_leaves_room_for_relevance(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(loop.settings, "memory_max_inject", 4)
    for i in range(6):
        await add_source(sessions, f"rule-{i}", "常驻规则" * 400, recall_policy="always", importance=0.9 - i * 0.01)
    await add_source(sessions, "backend", "After fixing the Python backend, restart and verify.", importance=0.3)
    memory = SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "Fix the Python backend", set(), "default")
    keys = [json.loads(item)["key"] for item in (await payload(memory, {1}, "default"))[1]]
    assert "backend" in keys
    assert sum(k.startswith("rule-") for k in keys) <= 2


async def test_revocation_and_failed_adapter_handoff_do_not_emit_cards(sessions, tmp_path, monkeypatch):
    await add_source(sessions, "backend", "Original")
    memory = SessionMemory(7, 1, "main", str(tmp_path))
    context = AgentContext(workspace=tmp_path, model="gpt-4o")
    context.metadata.update(_session_memory=memory, _current_memory_anchor=1)
    context.messages = [{"role": "user", "content": "backend", ANCHOR_ID: 1}]
    events = []
    context.event_bus.subscribe(events.append)
    await memory.prepare(1, "backend", set(), "default")
    send = AsyncMock(side_effect=RuntimeError("network error"))
    monkeypatch.setattr(loop.litellm, "acompletion", send)
    admission = Admission()
    with pytest.raises(RuntimeError, match="network error"):
        await loop._complete(context, admission)
    assert "Original" in json.dumps(send.call_args.kwargs["messages"])
    assert not events
    async with sessions.begin() as db:
        await db.execute(update(Source).values(content="Updated"))
    send.side_effect = None
    await loop._complete(context, admission)
    assert "session-memory-reference>" not in json.dumps(send.call_args.kwargs["messages"])
    assert not events


async def test_history_restores_only_valid_admitted_receipts(sessions, tmp_path):
    await add_source(sessions, "backend", "Do not include this body in the response")
    await add_source(sessions, "unused", "Never dispatched")
    memory = SessionMemory(7, 1, "main", str(tmp_path))
    assert await memory.prepare(1, "backend", set(), "default")
    assert await memory.prepare(2, "unused", {1}, "default")
    assert 1 in await payload(memory, {1}, "default")

    async def history():
        async with sessions() as db:
            return await list_messages(
                "s", limit=None, branch=None, offset=0, include_compressed=True, user=SimpleNamespace(id=7), db=db
            )

    results = await history()
    cards = {row["id"]: row["memory_references"] for row in results if "memory_references" in row}
    assert list(cards) == [1]
    assert [ref["key"] for ref in cards[1]] == ["backend"]
    # Receipts expose only the stored digest — never the injected body.
    assert cards[1][0]["summary"] == ""
    assert cards[1][0]["memory_type"] == "team"
    assert "Do not include this body" not in json.dumps(results)
    async with sessions.begin() as db:
        await db.execute(delete(database.AgentMemory).where(database.AgentMemory.key == "backend"))
    assert not any("memory_references" in row for row in await history())
    assert await payload(memory, {1}, "default") == {}
