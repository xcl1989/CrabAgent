import asyncio
import logging
import os
import subprocess
import tempfile
import time
from typing import Any

from crabagent.core.agent.tools.registry import registry
from crabagent.core.agent.tools.sandbox import truncate_output, validate_command

logger = logging.getLogger(__name__)

# Emit BASH_OUTPUT events at most every N seconds
_EMIT_INTERVAL = 0.15

# When reading stream chunks, timeout per individual read() call.
# Prevents hanging if the process stalls without producing output.
_CHUNK_READ_TIMEOUT = 60


async def _emit_bash_output(context: Any, text: str, tool_call_id: str = "") -> None:
    """Emit a BASH_OUTPUT SSE event for real-time frontend display."""
    if not context or not hasattr(context, "event_bus") or not context.event_bus:
        return
    from crabagent.core.event import AgentEvent, EventType

    await context.event_bus.emit(
        AgentEvent(
            type=EventType.BASH_OUTPUT,
            data={"text": text, "tool_call_id": tool_call_id},
        )
    )


@registry.register(
    name="bash",
    description=(
        "Execute a bash command. For long-running services (dev servers, watchers), "
        "set background=true to run in background and return immediately. "
        "Do NOT use osascript or open new Terminal windows."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute.",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory for the command. Default: current directory.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds. Default: 120000.",
                "default": 120000,
            },
            "background": {
                "type": "boolean",
                "description": (
                    "Set true for long-running commands (dev servers, watchers, etc.). "
                    "Runs in background, returns immediately with PID."
                ),
                "default": False,
            },
        },
        "required": ["command"],
    },
    requires_permission=True,
)
async def bash_command(
    command: str,
    workdir: str | None = None,
    timeout: int = 120000,
    background: bool = False,
    context: Any = None,
) -> str:
    block_reason = validate_command(command)
    if block_reason:
        if block_reason.startswith("NEED_CONFIRM:"):
            detail = block_reason[len("NEED_CONFIRM:"):]
            if context and context.confirm_callback:
                approved = await context.confirm_callback("bash", {
                    "command": command,
                    "warning": detail,
                })
                if not approved:
                    return f"Command denied by user: {detail}"
            else:
                return f"⚠️ 安全提醒：该命令需要您确认 — {detail}\n\n是否允许执行？请回复 yes/no。"
        else:
            return block_reason

    if background:
        return await _run_background(command, workdir, context)

    # Source user profile to get correct PATH (macOS Python, homebrew, etc.)
    _profile_cmd = (
        "export SHELL=$(echo $SHELL 2>/dev/null || echo /bin/sh); "
        "[ -f ~/.zprofile ] && . ~/.zprofile; "
        "[ -f ~/.bash_profile ] && . ~/.bash_profile; "
        "[ -f ~/.profile ] && . ~/.profile; "
    )
    full_command = _profile_cmd + command

    try:
        proc = await asyncio.create_subprocess_shell(
            full_command,
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            start_new_session=True,
        )

        timeout_sec = timeout / 1000.0
        collected_stdout: list[str] = []
        collected_stderr: list[str] = []

        # Try to extract tool_call_id from context for SSE event correlation
        tool_call_id = ""
        if context and hasattr(context, "metadata"):
            tool_call_id = context.metadata.get("current_tool_call_id", "")

        try:
            await asyncio.wait_for(
                _stream_output(
                    proc,
                    collected_stdout,
                    collected_stderr,
                    context,
                    tool_call_id,
                ),
                timeout=timeout_sec,
            )
            # Process completed within timeout
            await proc.wait()
            full_out = "".join(collected_stdout)
            full_err = "".join(collected_stderr)
            return _format_result(full_out, full_err, proc.returncode)

        except TimeoutError:
            # Process still running after timeout → auto-background
            return await _auto_background(
                proc, collected_stdout, collected_stderr, command, timeout_sec, context
            )

    except Exception as e:
        return f"Error executing command: {e}"


async def _stream_output(
    proc: asyncio.subprocess.Process,
    stdout_sink: list[str],
    stderr_sink: list[str],
    context: Any,
    tool_call_id: str = "",
) -> None:
    """Read stdout/stderr in chunks, emit BASH_OUTPUT events in real-time."""

    async def _read_stream(
        stream: asyncio.StreamReader,
        sink: list[str],
        label: str,
    ) -> None:
        buf = ""
        last_emit = 0.0
        while True:
            try:
                chunk = await asyncio.wait_for(
                    stream.read(4096), timeout=_CHUNK_READ_TIMEOUT
                )
            except TimeoutError:
                # No data for a while, but process may still be running
                # Emit whatever we have buffered
                if buf:
                    await _emit_bash_output(context, buf, tool_call_id)
                    buf = ""
                    last_emit = time.monotonic()
                continue
            except Exception:
                break

            if not chunk:
                break

            text = chunk.decode("utf-8", errors="replace")
            sink.append(text)
            buf += text

            now = time.monotonic()
            # Emit when buffer accumulates enough or enough time has passed
            if len(buf) >= 4096 or (now - last_emit) >= _EMIT_INTERVAL:
                await _emit_bash_output(context, buf, tool_call_id)
                buf = ""
                last_emit = now

        # Flush remaining buffer
        if buf:
            await _emit_bash_output(context, buf, tool_call_id)

    await asyncio.gather(
        _read_stream(proc.stdout, stdout_sink, "stdout"),
        _read_stream(proc.stderr, stderr_sink, "stderr"),
    )


def _format_result(
    stdout: str,
    stderr: str,
    returncode: int,
    timed_out: bool = False,
    timeout_sec: float = 0,
) -> str:
    """Format command output into a string result."""
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    if returncode != 0:
        parts.append(f"[exit code: {returncode}]")
    if timed_out:
        parts.append(f"[timed out after {timeout_sec:.0f}s]")
    output = "\n".join(parts) if parts else "[no output]"
    return truncate_output(output)


async def _auto_background(
    proc: asyncio.subprocess.Process,
    collected_stdout: list[str],
    collected_stderr: list[str],
    command: str,
    timeout_sec: float,
    context: Any,
) -> str:
    """Process exceeded timeout — redirect remaining output to a log file and return."""

    pid = proc.pid
    log_dir = tempfile.gettempdir()
    log_file = os.path.join(log_dir, f"crabagent-bg-{pid}.log")

    # Write already-collected output to log file
    try:
        with open(log_file, "w") as f:
            f.write("".join(collected_stdout))
            if collected_stderr:
                f.write("\n[stderr]\n")
                f.write("".join(collected_stderr))
    except Exception:
        pass

    # Redirect process remaining output to log file (append mode)
    try:
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        if proc.stdout:
            asyncio.ensure_future(_drain_to_fd(proc.stdout, log_fd))
        if proc.stderr:
            asyncio.ensure_future(_drain_to_fd(proc.stderr, log_fd, prefix=b"[stderr] "))
    except Exception:
        pass

    # Emit final event to inform frontend
    try:
        tool_call_id = ""
        if context and hasattr(context, "metadata"):
            tool_call_id = context.metadata.get("current_tool_call_id", "")
        await _emit_bash_output(
            context,
            (
                f"\n⏳ 命令执行超过 {timeout_sec:.0f}s，已自动转入后台\n"
                f"   PID: {pid}\n"
                f"   日志: {log_file}\n"
            ),
            tool_call_id,
        )
    except Exception:
        pass

    # Check if process is still alive
    await asyncio.sleep(1)
    status_line = ""
    try:
        check = await asyncio.create_subprocess_shell(
            f"ps -p {pid} -o pid=,command=",
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(check.communicate(), timeout=5)
        if out.strip():
            status_line = f"  command: {out.decode().strip()}\n"
    except Exception:
        pass

    partial_out = "".join(collected_stdout)
    partial_err = "".join(collected_stderr)
    result = _format_result(partial_out, partial_err, -1)

    return (
        f"{result}\n"
        f"[auto-background] 命令超过 {timeout_sec:.0f}s 仍在运行，已转入后台\n"
        f"  PID: {pid}\n"
        f"{status_line}"
        f"  日志: {log_file}\n"
        f"  查看最新输出: tail -50 {log_file}\n"
        f"  终止: kill {pid}\n"
    )


async def _drain_to_fd(
    stream: asyncio.StreamReader,
    fd: int,
    max_bytes: int = 500_000,
    prefix: bytes = b"",
) -> None:
    """Drain remaining stream output to a file descriptor."""
    collected = 0
    wrote_prefix = not prefix  # Skip prefix on first write if empty
    try:
        while collected < max_bytes:
            try:
                chunk = await asyncio.wait_for(stream.read(4096), timeout=5)
            except Exception:
                break
            if not chunk:
                break
            if not wrote_prefix:
                os.write(fd, prefix)
                wrote_prefix = True
            os.write(fd, chunk)
            collected += len(chunk)
    except Exception:
        pass
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


async def _run_background(
    command: str, workdir: str | None = None, context: Any = None
) -> str:
    """Start command in background via nohup and return immediately."""

    log_dir = tempfile.gettempdir()
    pid = os.getpid()
    log_file = os.path.join(log_dir, f"crabagent-bg-{pid}.log")

    _profile_cmd = (
        "export SHELL=$(echo $SHELL 2>/dev/null || echo /bin/sh); "
        "[ -f ~/.zprofile ] && . ~/.zprofile; "
        "[ -f ~/.bash_profile ] && . ~/.bash_profile; "
        "[ -f ~/.profile ] && . ~/.profile; "
    )
    wrapped = f"nohup {_profile_cmd} {command} > {log_file} 2>&1 & echo $!"

    try:
        proc = await asyncio.create_subprocess_shell(
            wrapped,
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            start_new_session=True,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        pid_str = stdout.decode("utf-8", errors="replace").strip()
        err_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0 or not pid_str:
            return f"[background] failed to start\n{err_str}"

        # Emit event for frontend
        await _emit_bash_output(
            context,
            f"[background] PID={pid_str} — process started\n  log: {log_file}\n",
        )

        await asyncio.sleep(1)
        try:
            check = await asyncio.create_subprocess_shell(
                f"ps -p {pid_str} -o pid=,command=",
                stdin=subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(check.communicate(), timeout=5)
            if out.strip():
                return (
                    f"[background] PID={pid_str} — process is running\n"
                    f"  command: {out.decode().strip()}\n"
                    f"  log: {log_file}\n"
                    f"  tail: tail -f {log_file}"
                )
        except Exception:
            pass

        return f"[background] PID={pid_str}\n  log: {log_file}\n  check: ps -p {pid_str}"
    except TimeoutError:
        proc.kill()
        return "[background] error: shell timed out starting background process"
    except Exception as e:
        return f"[background] error: {e}"
