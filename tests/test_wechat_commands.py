import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.core.wechat.client import IncomingMessage
from crabagent.core.wechat.config import WeChatConfig
from crabagent.core.wechat.message import WeChatMessageLoop


@pytest.mark.asyncio
async def test_commands_do_not_enter_active_followups(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    context = SimpleNamespace(workspace=tmp_path, model="model-a", metadata={"_accept_followups": True})
    loop._active_runs["alice"] = {"task": task, "context": context, "ready": asyncio.Event()}
    await loop._dispatch(IncomingMessage(from_user="alice", content="/状态", msg_id="1"))
    assert "model-a" in client.send_message.await_args.kwargs["text"]
    assert "_pending_user_messages" not in context.metadata
    release.set()
    await task


@pytest.mark.asyncio
async def test_unauthorized_command_is_not_answered(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    await loop._dispatch(IncomingMessage(from_user="bob", content="/帮助", msg_id="1"))
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    await loop._dispatch(IncomingMessage(from_user="alice", content="/模型 example", msg_id="1"))
    assert "配置未更改" in client.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_scheduled_messages_preserve_sender_order():
    client = SimpleNamespace()
    loop = WeChatMessageLoop(client)
    release = asyncio.Event()
    started = asyncio.Event()
    seen = []

    async def dispatch(msg):
        if msg.content == "first":
            started.set()
            await release.wait()
        seen.append(msg.content)

    loop._dispatch = dispatch
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="first"))
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="second"))
    loop._schedule_dispatch(IncomingMessage(from_user="bob", content="other"))
    await started.wait()
    await asyncio.sleep(0.01)
    assert seen == ["other"]
    release.set()
    await asyncio.gather(*list(loop._dispatch_tails.values()))
    assert seen == ["other", "first", "second"]


@pytest.mark.asyncio
async def test_model_list_available_during_run(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    monkeypatch.setattr(
        "crabagent.core.provider_store.list_providers",
        AsyncMock(return_value=[SimpleNamespace(name="p", enabled=True)]),
    )
    monkeypatch.setattr(
        "crabagent.serve.api.provider.get_provider_models", AsyncMock(return_value=[{"id": "custom-model"}])
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    loop._active_runs["alice"] = {"task": task, "context": None, "ready": asyncio.Event()}
    await loop._dispatch(IncomingMessage(from_user="alice", content="/模型 p", msg_id="1"))
    assert "custom-model" in client.send_message.await_args.kwargs["text"]
    await loop._dispatch(IncomingMessage(from_user="alice", content="/模型 p custom-model", msg_id="2"))
    assert "等待完成" in client.send_message.await_args.kwargs["text"]
    release.set()
    await task


@pytest.mark.asyncio
async def test_empty_compression_summary_preserves_history(monkeypatch):
    from crabagent.core.agent.compress import compress_context
    from crabagent.core.config import settings

    messages = [{"role": "user", "content": str(i)} for i in range(settings.context_keep_recent + 3)]
    context = SimpleNamespace(
        messages=messages, metadata={}, locale="en", event_bus=SimpleNamespace(emit=AsyncMock()), system_prompt=""
    )
    monkeypatch.setattr("crabagent.core.agent.compress.summarize_messages", AsyncMock(return_value="  "))
    await compress_context(context, {}, "model")
    assert context.messages is messages


@pytest.mark.asyncio
async def test_switch_queued_while_earlier_followup_waits(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    release = asyncio.Event()
    started = asyncio.Event()

    async def handler(msg, active):
        active["ready"].set()
        started.set()
        await release.wait()

    loop._default_handler = handler
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="first", msg_id="1"))
    await started.wait()
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="followup", msg_id="2"))
    await asyncio.sleep(0.01)
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="/新会话", msg_id="3"))
    for _ in range(100):
        if client.send_message.await_count:
            break
        await asyncio.sleep(0.001)
    assert "已排队" in client.send_message.await_args.kwargs["text"]
    release.set()
    await asyncio.gather(*list(loop._dispatch_tails.values()))
    await asyncio.gather(*(entry["task"] for entry in list(loop._active_runs.values())))


@pytest.mark.asyncio
async def test_deferred_switch_orders_following_messages_and_preserves_snapshot(monkeypatch):
    cfg = WeChatConfig(enabled=True, allowed_users=["alice"])
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    started, release = asyncio.Event(), asyncio.Event()
    seen = []
    selection = {"value": "old"}

    async def handler(msg, active):
        snapshot = selection["value"]
        seen.append(("start", msg.content, snapshot))
        active["ready"].set()
        if msg.content == "first":
            started.set()
            await release.wait()
            seen.append(("finish", snapshot, selection["value"]))

    async def command(msg):
        seen.append(("switch", msg.content))
        selection["value"] = msg.content
        return True

    loop._default_handler = handler
    loop._handle_command = command
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="first", msg_id="1"))
    await started.wait()
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="/新会话", msg_id="2"))
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="/工作空间 next", msg_id="3"))
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="after", msg_id="4"))
    await asyncio.sleep(0.02)
    assert len(client.send_message.await_args_list) == 2
    assert all("重启" in call.kwargs["text"] for call in client.send_message.await_args_list)
    assert seen == [("start", "first", "old")]
    release.set()
    await asyncio.gather(*list(loop._dispatch_tasks))
    await asyncio.gather(*(entry["task"] for entry in list(loop._active_runs.values())))
    assert seen == [
        ("start", "first", "old"),
        ("finish", "old", "old"),
        ("switch", "/新会话"),
        ("switch", "/工作空间 next"),
        ("start", "after", "/工作空间 next"),
    ]


@pytest.mark.asyncio
async def test_pending_switch_is_not_restored_by_new_loop(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    release = asyncio.Event()
    running = asyncio.create_task(release.wait())
    loop._active_runs["alice"] = {"task": running, "ready": asyncio.Event(), "context": None}
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="/新会话", msg_id="1"))
    await asyncio.sleep(0.02)
    assert "重启" in client.send_message.await_args.kwargs["text"]
    restarted = WeChatMessageLoop(client)
    assert not restarted._dispatch_tails
    for task in list(loop._dispatch_tasks):
        task.cancel()
    await asyncio.gather(*list(loop._dispatch_tasks), return_exceptions=True)
    release.set()
    await running


@pytest.mark.asyncio
async def test_cancelled_active_run_does_not_discard_switch(monkeypatch):
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, allowed_users=["alice"])),
    )
    loop = WeChatMessageLoop(SimpleNamespace(send_message=AsyncMock()))
    active = asyncio.create_task(asyncio.Event().wait())
    loop._active_runs["alice"] = {"task": active, "ready": asyncio.Event(), "context": None}
    command = AsyncMock(return_value=True)
    loop._handle_command = command
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="/新会话", msg_id="cancel-active"))
    await asyncio.sleep(0.01)
    active.cancel()
    await asyncio.gather(active, return_exceptions=True)
    await asyncio.gather(*list(loop._dispatch_tasks))
    command.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_previous_dispatch_does_not_cancel_next():
    loop = WeChatMessageLoop(SimpleNamespace())
    started = asyncio.Event()
    seen = []

    async def dispatch(msg):
        if msg.content == "first":
            started.set()
            await asyncio.Event().wait()
        seen.append(msg.content)

    loop._dispatch = dispatch
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="first"))
    await started.wait()
    previous = loop._dispatch_tails["alice"]
    loop._schedule_dispatch(IncomingMessage(from_user="alice", content="second"))
    previous.cancel()
    await asyncio.gather(*list(loop._dispatch_tasks), return_exceptions=True)
    assert seen == ["second"]
