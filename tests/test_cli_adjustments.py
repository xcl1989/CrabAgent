import asyncio
import io
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crabagent.cli import __main__ as cli


def invoke(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["crabagent", *argv])
    cli.main()


@pytest.mark.parametrize("argv", [["provider", "list"], ["provider list"]])
def test_provider_fails_cleanly(monkeypatch, capsys, argv):
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, argv)
    assert exc.value.code == 2
    assert "unavailable" in capsys.readouterr().err


def test_explicit_query_and_iteration(monkeypatch):
    seen = []

    async def run(args):
        seen.append(args)

    monkeypatch.setattr(cli, "_run_single", run)
    invoke(monkeypatch, ["--max-iterations", "7", "--query", "provider list"])
    assert seen[0].query == "provider list"
    assert seen[0].max_iterations == 7


def test_normal_argv_skill(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_dispatch_skill", lambda args: seen.append(args))
    invoke(monkeypatch, ["skill", "show", "example"])
    assert seen == [["show", "example"]]


def test_no_tty_and_no_query(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, [])
    assert exc.value.code == 2


def test_invalid_iterations(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, ["--max-iterations", "0", "hello"])
    assert exc.value.code == 2


def test_provider_setup_noninteractive(monkeypatch):
    import crabagent.core.provider_store as store

    monkeypatch.setattr(store, "list_providers", AsyncMock(return_value=[]))
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert asyncio.run(cli._ensure_provider_configured()) is False


def test_legacy_user_is_disabled_without_changing_identity(monkeypatch):
    import crabagent.core.auth_utils as auth
    import crabagent.core.database as database

    user = SimpleNamespace(id=42, enabled=True, password_hash="legacy", role="admin")
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: user)

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(database, "async_session_factory", Session)
    monkeypatch.setattr(auth, "verify_password", lambda password, hashed: hashed == "legacy")
    result = asyncio.run(cli._ensure_cli_user("cli_user"))
    assert result is user and result.id == 42 and result.role == "admin"
    assert not result.enabled
    db.commit.assert_awaited_once()


def test_custom_password_user_is_not_disabled(monkeypatch):
    import crabagent.core.auth_utils as auth
    import crabagent.core.database as database

    user = SimpleNamespace(id=43, enabled=True, password_hash="custom")
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: user)

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(database, "async_session_factory", Session)
    monkeypatch.setattr(auth, "verify_password", lambda password, hashed: False)
    assert asyncio.run(cli._ensure_cli_user("cli_user")) is user
    assert user.enabled
    db.commit.assert_not_awaited()


def test_single_and_tui_share_cli_identity():
    import inspect

    from crabagent.cli import __main__ as cli_main

    single_src = inspect.getsource(cli_main._run_single)
    interactive_src = inspect.getsource(cli_main._run_interactive)
    assert single_src.count('_ensure_cli_user("cli_user")') == 1
    assert interactive_src.count('_ensure_cli_user("cli_user")') == 1
    assert '_ensure_cli_user()' not in single_src
