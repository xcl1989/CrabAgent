from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base, Conversation
from crabagent.core.wechat import selection
from crabagent.core.wechat.message import _find_or_create_wechat_conversation, _wechat_identity_title


@pytest.mark.asyncio
async def test_selection_persistence_and_session_isolation(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(selection, "async_session_factory", factory)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", factory)
    title = _wechat_identity_title("bot", "alice")
    first = await _find_or_create_wechat_conversation("alice", title, "/a", "m")
    second = await _find_or_create_wechat_conversation("alice", title, "/a", "m", selected_id=0)
    other = await _find_or_create_wechat_conversation("alice", title, "/b", "m")
    await selection.save("bot", "alice", {"sessions": {"/a": first[1], "/b": other[1]}})
    state = await selection.load("bot", "alice")
    assert state["sessions"]["/a"] == first[1] != second[1]
    assert await selection.load("bot", "bob") == {}
    assert await selection.load("other-bot", "alice") == {}
    assert (await _find_or_create_wechat_conversation("alice", title, "/a", "m", selected_id=first[1]))[1] == first[1]
    with pytest.raises(ValueError):
        await _find_or_create_wechat_conversation(
            "bob", _wechat_identity_title("bot", "bob"), "/a", "m", selected_id=first[1]
        )
    with pytest.raises(ValueError):
        await _find_or_create_wechat_conversation("alice", title, "/b", "m", selected_id=first[1])
    await engine.dispose()


@pytest.mark.asyncio
async def test_model_command_persists_provider_and_rejects_unknown(monkeypatch, tmp_path):
    from crabagent.core.wechat.client import IncomingMessage
    from crabagent.core.wechat.config import WeChatConfig
    from crabagent.core.wechat.message import WeChatMessageLoop

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(selection, "async_session_factory", factory)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", factory)
    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config",
        AsyncMock(return_value=WeChatConfig(enabled=True, account_id="bot", allowed_users=["alice"])),
    )
    monkeypatch.setattr(
        "crabagent.core.provider_store.list_providers",
        AsyncMock(return_value=[SimpleNamespace(name="p", enabled=True)]),
    )
    monkeypatch.setattr("crabagent.serve.api.provider.get_provider_models", AsyncMock(return_value=[{"id": "m"}]))
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    await loop._dispatch(IncomingMessage(from_user="alice", content="/模型 p m", msg_id="1"))
    assert (await selection.load("bot", "alice"))["provider"] == "p"
    assert (await selection.load("bot", "alice"))["model"] == "m"
    await loop._dispatch(IncomingMessage(from_user="alice", content="/模型 p nope", msg_id="2"))
    assert (await selection.load("bot", "alice"))["model"] == "m"
    assert await selection.load("bot", "bob") == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_desktop_workspace_grants_and_command_selection(tmp_path, monkeypatch):
    from crabagent.core.wechat.client import IncomingMessage
    from crabagent.core.wechat.config import WeChatConfig
    from crabagent.core.wechat.message import WeChatMessageLoop

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/workspaces.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(selection, "async_session_factory", factory)
    default, desktop, private, missing = [tmp_path / n for n in ("default", "desktop", "private", "missing")]
    for path in (default, desktop, private):
        path.mkdir()
    async with factory() as db:
        db.add_all(
            [
                Conversation(session_id="desktop", user_id=1, workspace=str(desktop), source="chat"),
                Conversation(session_id="private", user_id=2, workspace=str(private), source="chat"),
                Conversation(session_id="wechat", user_id=1, workspace=str(private), source="wechat"),
            ]
        )
        await db.commit()
    cfg = WeChatConfig(
        enabled=True,
        account_id="bot",
        allowed_users=["alice"],
        workspace=str(default),
        allowed_workspaces=[str(desktop), str(private), str(missing)],
    )
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    client = SimpleNamespace(send_message=AsyncMock())
    loop = WeChatMessageLoop(client)
    await loop._dispatch(IncomingMessage(from_user="alice", content="/工作空间", msg_id="1"))
    text = client.send_message.await_args.kwargs["text"]
    assert str(desktop) in text and str(default) in text and str(private) not in text and str(missing) not in text
    await loop._dispatch(IncomingMessage(from_user="alice", content=f"/工作空间 {desktop}", msg_id="2"))
    assert (await selection.load("bot", "alice"))["workspace"] == str(desktop)
    await loop._dispatch(IncomingMessage(from_user="alice", content=f"/工作空间 {private}", msg_id="3"))
    assert (await selection.load("bot", "alice"))["workspace"] == str(desktop)
    cfg.allowed_workspaces = []
    assert str(desktop) not in await selection.available_workspaces(cfg)
    await engine.dispose()


@pytest.mark.asyncio
async def test_workspace_grants_api_checks_owner_and_registration(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from crabagent.core.wechat.config import WeChatConfig
    from crabagent.serve.api.wechat import UpdateConfigRequest, update_config

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(selection, "async_session_factory", factory)
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    async with factory() as db:
        db.add(Conversation(session_id="chat", user_id=1, workspace=str(desktop), source="chat"))
        await db.commit()
    cfg = WeChatConfig(workspace=str(tmp_path))
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    monkeypatch.setattr("crabagent.core.wechat.config.save_config", AsyncMock())
    monkeypatch.setattr("crabagent.serve.api.wechat._stop_message_loop", AsyncMock())
    request = UpdateConfigRequest(allowed_workspaces=[str(desktop)])
    with pytest.raises(HTTPException) as err:
        await update_config(request, SimpleNamespace(id=2, role="user"))
    assert err.value.status_code == 403
    with pytest.raises(HTTPException):
        await update_config(
            UpdateConfigRequest(allowed_workspaces=[str(tmp_path / "no")]), SimpleNamespace(id=1, role="admin")
        )
    await update_config(request, SimpleNamespace(id=1, role="admin"))
    assert cfg.allowed_workspaces == [str(desktop)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_revoked_workspace_blocks_agent_run(tmp_path, monkeypatch):
    from crabagent.core.wechat.client import IncomingMessage
    from crabagent.core.wechat.config import WeChatConfig
    from crabagent.core.wechat.message import _run_agent_for_wechat

    monkeypatch.setattr(
        "crabagent.core.wechat.config.load_config", AsyncMock(return_value=WeChatConfig(workspace=str(tmp_path)))
    )
    monkeypatch.setattr(selection, "load", AsyncMock(return_value={"workspace": str(tmp_path / "revoked")}))
    monkeypatch.setattr(selection, "available_workspaces", AsyncMock(return_value=[str(tmp_path)]))
    with pytest.raises(ValueError, match="授权已撤销"):
        await _run_agent_for_wechat(IncomingMessage(from_user="alice", content="hello"))


@pytest.mark.asyncio
async def test_restores_active_summary_in_sequence_order(tmp_path, monkeypatch):
    from crabagent.core.database import Message

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/history.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("crabagent.core.database.async_session_factory", factory)
    title = _wechat_identity_title("bot", "alice")
    _, conv_id, _ = await _find_or_create_wechat_conversation("alice", title, "/a", "m")
    async with factory() as db:
        db.add_all(
            [
                Message(
                    conversation_id=conv_id, sequence=1, role="user", content="old", branch_id="main", compressed=True
                ),
                Message(
                    conversation_id=conv_id,
                    sequence=3,
                    role="user",
                    content="recent",
                    branch_id="main",
                    compressed=False,
                ),
                Message(
                    conversation_id=conv_id,
                    sequence=2,
                    role="compress",
                    content="summary",
                    branch_id="main",
                    compressed=False,
                ),
            ]
        )
        await db.commit()
    _, _, history = await _find_or_create_wechat_conversation("alice", title, "/a", "m", selected_id=conv_id)
    assert [(m["role"], m["content"]) for m in history] == [("compress", "summary"), ("user", "recent")]
    await engine.dispose()
