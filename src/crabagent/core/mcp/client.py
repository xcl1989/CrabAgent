from __future__ import annotations

import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


def _ensure_node_path(config_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build an environment dict with a PATH that includes common node/npm locations.

    When CrabAgent runs as a background service, the inherited PATH may not
    include /usr/local/bin or /opt/homebrew/bin where node/npx/npm live.
    """
    import os

    env = dict(config_env or {})
    if not env:
        env = dict(os.environ)
    current_path = env.get("PATH", os.environ.get("PATH", ""))
    extra_dirs = ["/usr/local/bin", "/opt/homebrew/bin", os.path.expanduser("~/.nvm/versions/node/current/bin")]
    parts = current_path.split(":") if current_path else []
    for d in extra_dirs:
        if d not in parts:
            parts.append(d)
    env["PATH"] = ":".join(parts)
    return env


def _get_schema(tool) -> dict[str, Any]:
    if hasattr(tool, "inputSchema"):
        return tool.inputSchema
    if hasattr(tool, "input_schema"):
        return tool.input_schema
    return {}


@dataclass
class McpServerConfig:
    name: str
    display_name: str
    transport: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row) -> McpServerConfig:
        return cls(
            name=row.name,
            display_name=row.display_name,
            transport=row.transport,
            command=row.command or "",
            args=json.loads(row.args) if row.args else [],
            url=row.url or "",
            env=json.loads(row.env) if row.env else {},
            headers=json.loads(row.headers) if row.headers else {},
        )


@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class McpConnection:
    def __init__(self, config: McpServerConfig, quiet: bool = False):
        self.config = config
        self.quiet = quiet
        self._stderr_log: TextIO | None = None
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[McpToolInfo] = []
        self.status: str = "disconnected"
        self.last_error: str = ""
        self.connected_at: float | None = None

    @property
    def is_connected(self) -> bool:
        return self.status == "connected" and self._session is not None

    async def connect(self, timeout: float = 30.0) -> list[McpToolInfo]:
        """Connect with a timeout to avoid blocking indefinitely on
        unresponsive servers."""
        import asyncio

        self.status = "connecting"
        self.last_error = ""
        self._exit_stack = AsyncExitStack()
        try:
            if self.config.transport == "http":
                tools = await asyncio.wait_for(self._connect_http(), timeout=timeout)
            else:
                tools = await asyncio.wait_for(self._connect_stdio(), timeout=timeout)
            self._tools = tools
            self.status = "connected"
            self.connected_at = time.time()
            return tools
        except asyncio.TimeoutError:
            self.last_error = f"Connection timed out after {timeout}s"
            self.status = "error"
            await self._cleanup()
            raise
        except Exception as e:
            self.last_error = str(e)
            self.status = "error"
            await self._cleanup()
            raise

    async def _connect_stdio(self) -> list[McpToolInfo]:
        # Merge user-provided env with a PATH that includes common node locations
        full_env = _ensure_node_path(self.config.env)
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=full_env,
        )
        if self.quiet:
            import os

            self._stderr_log = open(os.devnull, "w")
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params, errlog=self._stderr_log) if self._stderr_log else stdio_client(params)
        )
        self._session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self._session.initialize()
        return await self._discover_tools()

    async def _connect_http(self) -> list[McpToolInfo]:
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        client = httpx.AsyncClient(
            headers=self.config.headers,
            timeout=httpx.Timeout(30.0, read=300.0),
        )
        await self._exit_stack.enter_async_context(client)

        transport_ctx = streamable_http_client(
            self.config.url,
            http_client=client,
        )
        streams = await self._exit_stack.enter_async_context(transport_ctx)
        read_stream, write_stream, _ = streams

        self._session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self._session.initialize()
        return await self._discover_tools()

    async def _discover_tools(self) -> list[McpToolInfo]:
        assert self._session is not None
        result = await self._session.list_tools()
        return [
            McpToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=_get_schema(t),
                server_name=self.config.name,
            )
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if not self._session:
            raise RuntimeError(f"Not connected to MCP server '{self.config.name}'")
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as e:
            self.status = "error"
            self.last_error = str(e)
            raise
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        text = "\n".join(parts)
        if result.isError:
            text = f"[MCP Error] {text}"
        return text

    async def disconnect(self):
        await self._cleanup()
        self.status = "disconnected"

    async def _cleanup(self):
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._session = None
        self._exit_stack = None
        self._tools = []
        if self._stderr_log:
            self._stderr_log.close()
            self._stderr_log = None

    def get_status_dict(self) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "display_name": self.config.display_name,
            "status": self.status,
            "tool_count": len(self._tools),
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in self._tools
            ],
            "error": self.last_error,
            "connected_at": self.connected_at,
        }


class MCPClientManager:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self._connections: dict[str, McpConnection] = {}

    async def start_server(self, config: McpServerConfig) -> list[McpToolInfo]:
        if config.name in self._connections:
            await self.stop_server(config.name)
        conn = McpConnection(config, quiet=self.quiet)
        try:
            tools = await conn.connect()
        except Exception:
            self._connections[config.name] = conn
            logger.warning("MCP server '%s' failed to connect: %s", config.name, conn.last_error)
            raise
        self._connections[config.name] = conn
        logger.info("MCP server '%s' connected, %d tools discovered", config.name, len(tools))
        return tools

    async def stop_server(self, name: str):
        conn = self._connections.get(name)
        if conn:
            await conn.disconnect()
            logger.info("MCP server '%s' disconnected", name)
            del self._connections[name]

    async def stop_all(self):
        names = list(self._connections.keys())
        for name in names:
            await self.stop_server(name)

    async def start_all(self):
        """Connect to all enabled MCP servers in parallel.

        Each server's failure is logged but never propagates — one bad
        server must not block the rest.
        """
        import asyncio

        configs = await load_enabled_servers()
        if not configs:
            return

        async def _safe_start(config: McpServerConfig):
            try:
                await self.start_server(config)
            except Exception:
                pass  # already logged in start_server

        await asyncio.gather(*[_safe_start(c) for c in configs], return_exceptions=True)

    def get_connection(self, server_name: str) -> McpConnection | None:
        return self._connections.get(server_name)

    def get_all_connections(self) -> dict[str, McpConnection]:
        return dict(self._connections)

    def get_status(self) -> list[dict[str, Any]]:
        return [conn.get_status_dict() for conn in self._connections.values()]

    def get_connected_tools(self) -> list[McpToolInfo]:
        tools = []
        for conn in self._connections.values():
            if conn.is_connected:
                tools.extend(conn._tools)
        return tools


async def load_enabled_servers() -> list[McpServerConfig]:
    from crabagent.core.database import async_session_factory

    configs = []
    async with async_session_factory() as db:
        from sqlalchemy import select

        from crabagent.core.database import McpServer

        result = await db.execute(select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name))
        for row in result.scalars().all():
            configs.append(McpServerConfig.from_row(row))
    return configs
