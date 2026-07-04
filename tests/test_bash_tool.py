"""Tests for the bash command execution tool."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools import bash as bash_tool
from crabagent.core.agent.tools.bash import bash_command, _format_result


# ── _format_result ────────────────────────────────────────────────────


class TestFormatResult:
    def test_stdout_only(self):
        result = _format_result("hello", "", 0)
        assert result == "hello"

    def test_stdout_and_stderr(self):
        result = _format_result("out", "err", 0)
        assert "out" in result
        assert "[stderr]" in result
        assert "err" in result

    def test_nonzero_exit_code(self):
        result = _format_result("", "", 1)
        assert "[exit code: 1]" in result

    def test_no_output(self):
        result = _format_result("", "", 0)
        assert result == "[no output]"

    def test_timed_out(self):
        result = _format_result("partial", "", -1, timed_out=True, timeout_sec=30)
        assert "[timed out after 30s]" in result

    def test_truncates_long_output(self):
        long = "A" * 100000
        result = _format_result(long, "", 0)
        assert len(result) < 60000
        assert "truncated" in result


# ── validate_command integration ──────────────────────────────────────


class TestBashValidation:
    @pytest.mark.asyncio
    async def test_blocked_destructive_command_returns_error(self, tmp_path: Path):
        context = AgentContext(workspace=tmp_path)
        result = await bash_command("rm -rf /", context=context)
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_privilege_escalation(self, tmp_path: Path):
        context = AgentContext(workspace=tmp_path)
        result = await bash_command("sudo ls", context=context)
        assert "blocked" in result.lower() or "privilege" in result.lower()

    @pytest.mark.asyncio
    async def test_need_confirm_without_callback_returns_warning(self, tmp_path: Path):
        context = AgentContext(workspace=tmp_path)
        # Writing to /etc/passwd triggers NEED_CONFIRM
        result = await bash_command("echo data > /etc/passwd", context=context)
        assert "安全提醒" in result or "确认" in result

    @pytest.mark.asyncio
    async def test_need_confirm_denied_by_user(self, tmp_path: Path):
        denied = False

        async def fake_confirm(name, args):
            nonlocal denied
            denied = True
            return False

        context = AgentContext(workspace=tmp_path, confirm_callback=fake_confirm)
        result = await bash_command("echo data > /etc/passwd", context=context)
        assert denied is True
        assert "denied" in result.lower()

    @pytest.mark.asyncio
    async def test_need_confirm_approved_by_user(self, tmp_path: Path):
        approved = {"v": False}

        async def fake_confirm(name, args):
            approved["v"] = True
            return True

        context = AgentContext(workspace=tmp_path, confirm_callback=fake_confirm)
        # This will try to actually run the command after approval
        # It should not return the "需要确认" message
        result = await bash_command("echo data > /etc/passwd", context=context)
        assert approved["v"] is True
        assert "安全提醒" not in result
        assert "确认" not in result


# ── _build_subprocess_kwargs ──────────────────────────────────────────


class TestBuildSubprocessKwargs:
    def test_no_workdir(self):
        kwargs = bash_tool._build_subprocess_kwargs()
        assert "cwd" not in kwargs

    def test_with_workdir(self):
        kwargs = bash_tool._build_subprocess_kwargs("/tmp")
        assert kwargs.get("cwd") == "/tmp"

    def test_includes_process_group_flag(self):
        kwargs = bash_tool._build_subprocess_kwargs()
        if not bash_tool.IS_WINDOWS:
            assert kwargs.get("start_new_session") is True


# ── _emit_bash_output ─────────────────────────────────────────────────


class TestEmitBashOutput:
    @pytest.mark.asyncio
    async def test_noop_without_context(self):
        await bash_tool._emit_bash_output(None, "text")

    @pytest.mark.asyncio
    async def test_noop_without_event_bus(self):
        await bash_tool._emit_bash_output(SimpleNamespace(event_bus=None), "text")

    @pytest.mark.asyncio
    async def test_emits_event(self):
        events = []

        class FakeBus:
            async def emit(self, event):
                events.append(event)

        ctx = SimpleNamespace(event_bus=FakeBus())
        await bash_tool._emit_bash_output(ctx, "hello", "tc1")

        assert len(events) == 1
        assert events[0].data["text"] == "hello"
        assert events[0].data["tool_call_id"] == "tc1"


# ── _get_subprocess_env ───────────────────────────────────────────────


class TestGetSubprocessEnv:
    def test_returns_dict_with_path(self):
        env = bash_tool._get_subprocess_env()
        assert isinstance(env, dict)
        assert "PATH" in env or len(env) > 0


# ── process helpers ───────────────────────────────────────────────────


class TestProcessHelpers:
    @pytest.mark.asyncio
    async def test_check_process_alive_returns_empty_on_failure(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_create(*args, **kwargs):
            raise RuntimeError("ps missing")

        monkeypatch.setattr(bash_tool.asyncio, "create_subprocess_shell", fake_create)

        result = await bash_tool._check_process_alive(123)

        assert result == ""

    @pytest.mark.asyncio
    async def test_run_background_reports_failed_start(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        class FakeProc:
            returncode = 1

            async def communicate(self):
                return b"", b"boom"

        async def fake_create(*args, **kwargs):
            return FakeProc()

        monkeypatch.setattr(bash_tool.asyncio, "create_subprocess_shell", fake_create)
        monkeypatch.setattr(bash_tool.tempfile, "gettempdir", lambda: str(tmp_path))

        result = await bash_tool._run_background("echo hi")

        assert "failed to start" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_run_background_returns_running_status(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        events = []

        class FakeProc:
            returncode = 0

            async def communicate(self):
                return b"4321\n", b""

        async def fake_create(*args, **kwargs):
            return FakeProc()

        async def fake_emit(context, text, tool_call_id=""):
            events.append((text, tool_call_id))

        monkeypatch.setattr(bash_tool.asyncio, "create_subprocess_shell", fake_create)
        monkeypatch.setattr(bash_tool.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(bash_tool, "_emit_bash_output", fake_emit)
        monkeypatch.setattr(bash_tool, "_check_process_alive", _async_return("4321 /bin/sh -c echo hi"))
        monkeypatch.setattr(bash_tool.asyncio, "sleep", _async_noop)

        ctx = AgentContext(workspace=tmp_path)
        result = await bash_tool._run_background("echo hi", context=ctx)

        assert "process is running" in result
        assert "4321" in result
        assert events

    @pytest.mark.asyncio
    async def test_drain_to_fd_writes_prefix_once(self, tmp_path: Path):
        class FakeStream:
            def __init__(self):
                self.chunks = [b"abc", b"def", b""]

            async def read(self, size):
                return self.chunks.pop(0)

        path = tmp_path / "out.log"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        await bash_tool._drain_to_fd(FakeStream(), fd, prefix=b"[stderr] ")

        content = path.read_bytes()
        assert content == b"[stderr] abcdef"


# ── sandbox extra coverage ────────────────────────────────────────────


class TestSandboxExtra:
    def test_block_device_write(self):
        from crabagent.core.agent.tools.sandbox import validate_command

        assert validate_command("dd if=/dev/zero of=/dev/sda") is not None

    def test_fork_bomb_pattern(self):
        from crabagent.core.agent.tools.sandbox import validate_command

        assert validate_command(":(){ :|:& };:") is not None

    def test_safe_command_passes(self):
        from crabagent.core.agent.tools.sandbox import validate_command

        assert validate_command("echo hello") is None

    def test_background_pattern_blocked_when_enabled(self, monkeypatch):
        from crabagent.core.agent.tools import sandbox

        monkeypatch.setattr(sandbox.settings, "bash_block_background", True)
        result = sandbox.validate_command("tmux new-session")
        assert result is not None

    def test_truncate_output_with_custom_max(self):
        from crabagent.core.agent.tools.sandbox import truncate_output

        result = truncate_output("A" * 1000, max_length=100)
        assert len(result) < 300
        assert "truncated" in result


async def _async_noop(*args, **kwargs):
    return None


def _async_return(value):
    async def inner(*args, **kwargs):
        return value

    return inner
