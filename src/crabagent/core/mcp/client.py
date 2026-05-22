from __future__ import annotations

import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


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
    def __init__(self, config: McpServerConfig):
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[McpToolInfo] = []
        self.status: str = "disconnected"
        self.last_error: str = ""
        self.connected_at: float | None = None

    @property
    def is_connected(self) -> bool:
        return self.status == "connected" and self._session is not None

    async def connect(self) -> list[McpToolInfo]:
        self.status = "connecting"
        self.last_error = ""
        self._exit_stack = AsyncExitStack()
        try:
            if self.config.transport == "http":
                tools = await self._connect_http()
            else:
                tools = await self._connect_stdio()
            self._tools = tools
            self.status = "connected"
            self.connected_at = time.time()
            return tools
        except Exception as e:
            self.last_error = str(e)
            self.status = "error"
            await self._cleanup()
            raise

    async def _connect_stdio(self) -> list[McpToolInfo]:
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env if self.config.env else None,
        )
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
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

        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
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

    def get_status_dict(self) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "display_name": self.config.display_name,
            "status": self.status,
            "tool_count": len(self._tools),
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in self._tools
            ],
            "error": self.last_error,
            "connected_at": self.connected_at,
        }


class MCPClientManager:
    def __init__(self):
        self._connections: dict[str, McpConnection] = {}

    async def start_server(self, config: McpServerConfig) -> list[McpToolInfo]:
        if config.name in self._connections:
            await self.stop_server(config.name)
        conn = McpConnection(config)
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

    async def stop_all(self):
        names = list(self._connections.keys())
        for name in names:
            await self.stop_server(name)

    async def start_all(self):
        configs = await load_enabled_servers()
        for config in configs:
            try:
                await self.start_server(config)
            except Exception:
                pass

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

        result = await db.execute(
            select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name)
        )
        for row in result.scalars().all():
            configs.append(McpServerConfig.from_row(row))
    return configs
