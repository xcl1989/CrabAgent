from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crabagent.core.database import McpServer, User, get_db
from crabagent.core.mcp.client import MCPClientManager, McpServerConfig
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class McpServerResponse(BaseModel):
    name: str
    display_name: str
    transport: str
    command: str
    args: list[str]
    url: str
    env: dict[str, str]
    headers: dict[str, str]
    enabled: bool


class CreateMcpServerRequest(BaseModel):
    name: str
    display_name: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = []
    url: str = ""
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    enabled: bool = True


class UpdateMcpServerRequest(BaseModel):
    display_name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None


class McpToolResponse(BaseModel):
    name: str
    description: str
    input_schema: dict


class TestConnectionResponse(BaseModel):
    success: bool
    error: str = ""
    tools: list[McpToolResponse] = []


class McpServerStatusResponse(BaseModel):
    name: str
    display_name: str
    status: str
    tool_count: int
    tools: list[McpToolResponse]
    error: str
    connected_at: float | None


def _to_response(row: McpServer) -> McpServerResponse:
    return McpServerResponse(
        name=row.name,
        display_name=row.display_name,
        transport=row.transport,
        command=row.command or "",
        args=json.loads(row.args) if row.args else [],
        url=row.url or "",
        env=json.loads(row.env) if row.env else {},
        headers=json.loads(row.headers) if row.headers else {},
        enabled=row.enabled,
    )


def _get_manager(request: Request) -> MCPClientManager:
    return request.app.state.mcp_manager


@router.get("", response_model=list[McpServerResponse])
async def list_mcp_servers(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(McpServer).order_by(McpServer.name))
    return [_to_response(row) for row in result.scalars().all()]


@router.post("", response_model=McpServerResponse, status_code=201)
async def create_mcp_server(
    req: CreateMcpServerRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(McpServer).where(McpServer.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="MCP server already exists")

    row = McpServer(
        name=req.name,
        display_name=req.display_name or req.name,
        transport=req.transport,
        command=req.command,
        args=json.dumps(req.args),
        url=req.url,
        env=json.dumps(req.env),
        headers=json.dumps(req.headers),
        enabled=req.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    if req.enabled:
        manager = _get_manager(request)
        config = McpServerConfig.from_row(row)
        try:
            await manager.start_server(config)
        except Exception as e:
            logger.warning("Auto-connect failed for new MCP server '%s': %s", req.name, e)

    return _to_response(row)


@router.patch("/{name}", response_model=McpServerResponse)
async def update_mcp_server(
    name: str,
    req: UpdateMcpServerRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    updates = req.model_dump(exclude_unset=True)

    config_changed = any(
        k in updates
        for k in ("transport", "command", "args", "url", "env", "headers")
    )

    if "args" in updates and updates["args"] is not None:
        updates["args"] = json.dumps(updates["args"])
    if "env" in updates and updates["env"] is not None:
        updates["env"] = json.dumps(updates["env"])
    if "headers" in updates and updates["headers"] is not None:
        updates["headers"] = json.dumps(updates["headers"])

    for key, value in updates.items():
        setattr(row, key, value)

    await db.commit()
    await db.refresh(row)

    manager = _get_manager(request)
    was_enabled = "enabled" in updates
    new_enabled = updates.get("enabled", row.enabled)

    if was_enabled and not new_enabled:
        await manager.stop_server(name)
    elif was_enabled and new_enabled:
        config = McpServerConfig.from_row(row)
        try:
            await manager.start_server(config)
        except Exception:
            pass
    elif config_changed:
        conn = manager.get_connection(name)
        if conn and conn.is_connected:
            config = McpServerConfig.from_row(row)
            try:
                await manager.start_server(config)
            except Exception:
                pass

    return _to_response(row)


@router.delete("/{name}", status_code=204)
async def delete_mcp_server(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    manager = _get_manager(request)
    await manager.stop_server(name)

    await db.delete(row)
    await db.commit()


@router.post("/{name}/test", response_model=TestConnectionResponse)
async def test_mcp_server(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    config = McpServerConfig.from_row(row)
    manager = MCPClientManager()
    try:
        tools = await manager.start_server(config)
        return TestConnectionResponse(
            success=True,
            tools=[
                McpToolResponse(name=t.name, description=t.description, input_schema=t.input_schema)
                for t in tools
            ],
        )
    except Exception as e:
        logger.warning("MCP test connection failed for '%s': %s", name, e)
        return TestConnectionResponse(success=False, error=str(e))
    finally:
        await manager.stop_all()


@router.get("/{name}/tools", response_model=list[McpToolResponse])
async def get_mcp_server_tools(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    manager = _get_manager(request)
    conn = manager.get_connection(name)
    if conn and conn.is_connected:
        return [
            McpToolResponse(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in conn._tools
        ]

    config = McpServerConfig.from_row(row)
    try:
        tools = await manager.start_server(config)
        return [
            McpToolResponse(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in tools
        ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect: {e}")


@router.get("/status/list", response_model=list[McpServerStatusResponse])
async def get_mcp_status(request: Request, user: User = Depends(get_current_user)):
    manager = _get_manager(request)
    statuses = manager.get_status()
    return [
        McpServerStatusResponse(
            name=s["name"],
            display_name=s["display_name"],
            status=s["status"],
            tool_count=s["tool_count"],
            tools=[McpToolResponse(**t) for t in s["tools"]],
            error=s["error"],
            connected_at=s["connected_at"],
        )
        for s in statuses
    ]


@router.post("/{name}/connect", response_model=McpServerStatusResponse)
async def connect_mcp_server(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    manager = _get_manager(request)
    config = McpServerConfig.from_row(row)

    try:
        await manager.start_server(config)
    except Exception as e:
        conn = manager.get_connection(name)
        if conn:
            status = conn.get_status_dict()
            return McpServerStatusResponse(
                name=status["name"],
                display_name=status["display_name"],
                status=status["status"],
                tool_count=status["tool_count"],
                tools=[McpToolResponse(**t) for t in status["tools"]],
                error=status["error"],
                connected_at=status["connected_at"],
            )
        raise HTTPException(status_code=502, detail=f"Failed to connect: {e}")

    conn = manager.get_connection(name)
    status = conn.get_status_dict()
    return McpServerStatusResponse(
        name=status["name"],
        display_name=status["display_name"],
        status=status["status"],
        tool_count=status["tool_count"],
        tools=[McpToolResponse(**t) for t in status["tools"]],
        error=status["error"],
        connected_at=status["connected_at"],
    )


@router.post("/{name}/disconnect", response_model=McpServerStatusResponse)
async def disconnect_mcp_server(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    manager = _get_manager(request)
    conn = manager.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail="MCP server not found in connection pool")

    await manager.stop_server(name)
    status = conn.get_status_dict()
    return McpServerStatusResponse(
        name=status["name"],
        display_name=status["display_name"],
        status=status["status"],
        tool_count=status["tool_count"],
        tools=[McpToolResponse(**t) for t in status["tools"]],
        error=status["error"],
        connected_at=status["connected_at"],
    )
