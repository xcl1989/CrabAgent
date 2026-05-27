import asyncio
import subprocess

from crabagent.core.agent.tools.registry import registry
from crabagent.core.agent.tools.sandbox import truncate_output, validate_command

_DETACH_TIMEOUT = 8


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
) -> str:
    block_reason = validate_command(command)
    if block_reason:
        return block_reason

    if background:
        return await _run_background(command, workdir)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DETACH_TIMEOUT)
        except TimeoutError:
            return await _detach_process(proc, command)

        parts = []
        if stdout:
            parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace')}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        output = "\n".join(parts) if parts else "[no output]"
        return truncate_output(output)
    except Exception as e:
        return f"Error executing command: {e}"


async def _detach_process(proc: asyncio.subprocess.Process, command: str) -> str:
    import os
    import tempfile

    pid = proc.pid
    log_dir = tempfile.gettempdir()
    log_file = os.path.join(log_dir, f"crabagent-bg-{pid}.log")

    try:
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        if proc.stdout:
            await _drain_to_file(proc.stdout, log_fd)
        os.close(log_fd)
    except Exception:
        pass

    await asyncio.sleep(2)
    try:
        check = await asyncio.create_subprocess_shell(
            f"ps -p {pid} -o pid=,command=",
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(check.communicate(), timeout=5)
        if out.strip():
            return (
                f"[auto-background] PID={pid} — process is still running\n"
                f"  command: {out.decode().strip()}\n"
                f"  log: {log_file}\n"
                f"  tail: tail -f {log_file}\n"
                f"  stop: kill {pid}"
            )
    except Exception:
        pass

    return f"[auto-background] PID={pid} — process may still be running\n  log: {log_file}\n  check: ps -p {pid}"


async def _drain_to_file(stream: asyncio.StreamReader, fd: int, max_bytes: int = 50000):
    import os as _os

    collected = 0
    try:
        while collected < max_bytes:
            chunk = await asyncio.wait_for(stream.read(4096), timeout=1)
            if not chunk:
                break
            _os.write(fd, chunk)
            collected += len(chunk)
    except Exception:
        pass


async def _run_background(command: str, workdir: str | None = None) -> str:
    import os
    import tempfile

    log_dir = tempfile.gettempdir()
    log_file = os.path.join(log_dir, f"crabagent-bg-{os.getpid()}.log")

    wrapped = f"nohup {command} > {log_file} 2>&1 & echo $!"

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
