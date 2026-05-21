from crabagent.core.agent.tools.registry import registry
from crabagent.core.agent.tools.sandbox import truncate_output, validate_command


@registry.register(
    name="bash",
    description="Execute a bash command in a persistent shell session. Returns stdout, stderr, and exit code.",
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
        },
        "required": ["command"],
    },
    requires_permission=True,
)
async def bash_command(command: str, workdir: str | None = None, timeout: int = 120000) -> str:
    import asyncio

    block_reason = validate_command(command)
    if block_reason:
        return block_reason

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout / 1000)
        parts = []
        if stdout:
            parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace')}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        output = "\n".join(parts) if parts else "[no output]"
        return truncate_output(output)
    except TimeoutError:
        proc.kill()
        return f"Error: command timed out after {timeout}ms"
    except Exception as e:
        return f"Error executing command: {e}"
