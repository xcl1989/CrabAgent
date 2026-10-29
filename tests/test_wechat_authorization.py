from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.core.wechat.client import IncomingMessage
from crabagent.core.wechat.config import WeChatConfig
from crabagent.core.wechat.message import WeChatMessageLoop


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cfg,user,expected",
    [
        (WeChatConfig(enabled=False), "alice", False),
        (WeChatConfig(enabled=True, auto_reply=False), "alice", False),
        (WeChatConfig(enabled=True, allowed_users=["alice"]), "bob", False),
        (WeChatConfig(enabled=True, allowed_users=["alice"]), "alice", True),
        (WeChatConfig(enabled=True), "alice", True),
        (WeChatConfig(enabled=True), "", False),
    ],
)
async def test_dispatch_authorization(monkeypatch, cfg, user, expected):
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    handler = AsyncMock()
    loop = WeChatMessageLoop(SimpleNamespace(), on_message=handler)
    loop._update_push_target = AsyncMock()
    await loop._dispatch(IncomingMessage(from_user=user, content="hello", context_token="token"))
    assert handler.await_count == int(expected)
    assert loop._update_push_target.await_count == int(expected)


@pytest.mark.asyncio
async def test_push_token_stays_bound_to_target(monkeypatch):
    cfg = WeChatConfig(notify_target_user="alice", cached_context_token="a")
    save = AsyncMock()
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    monkeypatch.setattr("crabagent.core.wechat.config.save_config", save)
    loop = WeChatMessageLoop(SimpleNamespace())
    await loop._update_push_target("bob", "b")
    assert cfg.cached_context_token == "a"
    save.assert_not_awaited()


def test_identity_key_is_stable_and_account_scoped():
    from crabagent.core.wechat.message import _wechat_identity_title

    assert _wechat_identity_title("bot", "alice") == _wechat_identity_title("bot", "alice")
    assert _wechat_identity_title("bot", "alice") != _wechat_identity_title("bot", "bob")
    assert _wechat_identity_title("bot", "alice") != _wechat_identity_title("other", "alice")


@pytest.mark.asyncio
async def test_user_grants_require_owner_and_normalize(monkeypatch):
    from fastapi import HTTPException

    from crabagent.serve.api.wechat import UpdateConfigRequest, update_config

    cfg = WeChatConfig()
    save = AsyncMock()
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    monkeypatch.setattr("crabagent.core.wechat.config.save_config", save)
    monkeypatch.setattr("crabagent.serve.api.wechat._stop_message_loop", AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await update_config(UpdateConfigRequest(allowed_users=["alice"]), SimpleNamespace(id=2, role="admin"))
    assert exc.value.status_code == 403
    save.assert_not_awaited()
    with pytest.raises(HTTPException) as exc:
        await update_config(UpdateConfigRequest(allowed_users=["alice"]), SimpleNamespace(id=1, role="admin"))
    assert exc.value.status_code == 400
    await update_config(UpdateConfigRequest(allowed_users=[]), SimpleNamespace(id=1, role="admin"))
    assert cfg.allowed_users == []
    with pytest.raises(HTTPException) as exc:
        await update_config(UpdateConfigRequest(allowed_users=["alice\nbob"]), SimpleNamespace(id=1, role="admin"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account,old_user,new_user,expected",
    [
        ("bot", "owner", "owner", []),
        ("bot", "", "owner", []),
        ("bot", "owner", "other", []),
        ("other", "owner", "owner", []),
        ("bot", "owner", "", []),
    ],
)
async def test_binding_migration_never_grants_sender(monkeypatch, account, old_user, new_user, expected):
    from crabagent.core.wechat.auth import _persist_credentials
    from crabagent.core.wechat.client import LoginCredentials

    cfg = WeChatConfig(
        account_id=account,
        ilink_user_id=old_user,
        allowed_users=["alice"],
        notify_target_user="alice",
        cached_context_token="token",
    )
    monkeypatch.setattr("crabagent.core.wechat.auth.load_config", AsyncMock(return_value=cfg))
    monkeypatch.setattr("crabagent.core.wechat.auth.save_config", AsyncMock())
    await _persist_credentials(LoginCredentials(bot_token="token", ilink_bot_id="bot", ilink_user_id=new_user))
    assert cfg.allowed_users == expected
    assert cfg.ilink_user_id == new_user
    if account != "bot" or not old_user or old_user != new_user:
        assert not cfg.notify_target_user and not cfg.cached_context_token
    else:
        assert cfg.notify_target_user == "alice" and cfg.cached_context_token == "token"


@pytest.mark.asyncio
async def test_bound_channel_accepts_all_senders(monkeypatch):
    cfg = WeChatConfig(enabled=True, ilink_user_id="owner")
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    handler = AsyncMock()
    loop = WeChatMessageLoop(SimpleNamespace(), on_message=handler)
    for sender in ("owner", "attacker"):
        await loop._dispatch(IncomingMessage(from_user=sender, content="hello"))
    assert handler.await_count == 2


def test_legacy_allowlist_migrates_to_single_binding():
    cfg = WeChatConfig.from_dict({"enabled": True, "bot_token": "token", "allowed_users": ["alice"]})
    assert cfg.enabled and cfg.bot_token == "token"
    assert cfg.allowed_users == []
    assert WeChatConfig.from_dict(cfg.to_dict()).allowed_users == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,auto_reply,sender,expected",
    [
        (True, True, "alice", True),
        (True, True, "bob", True),
        (False, True, "alice", False),
        (True, False, "alice", False),
        (True, True, "", False),
    ],
)
async def test_deferred_switch_single_binding(monkeypatch, enabled, auto_reply, sender, expected):
    cfg = WeChatConfig(enabled=enabled, auto_reply=auto_reply)
    monkeypatch.setattr("crabagent.core.wechat.config.load_config", AsyncMock(return_value=cfg))
    loop = WeChatMessageLoop(SimpleNamespace())
    result = await loop._prepare_deferred_switch(IncomingMessage(from_user=sender, content="/新会话"), False)
    assert result is expected
