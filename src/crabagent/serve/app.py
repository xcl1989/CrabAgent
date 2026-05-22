from __future__ import annotations

import importlib.resources
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from crabagent.core.database import init_db

    await init_db()
    logger.info("Database initialized")

    from crabagent.core.mcp.client import MCPClientManager

    manager = MCPClientManager()
    app.state.mcp_manager = manager
    try:
        await manager.start_all()
        logger.info("MCP servers initialized")
    except Exception:
        logger.warning("Failed to initialize some MCP servers")

    yield

    await manager.stop_all()
    logger.info("MCP servers stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CrabAgent",
        version="0.3.1",
        lifespan=lifespan,
    )
    app.state.event_queues = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from crabagent.serve.api.auth import router as auth_router
    from crabagent.serve.api.branch import router as branch_router
    from crabagent.serve.api.confirm import router as confirm_router
    from crabagent.serve.api.event import router as event_router
    from crabagent.serve.api.files import router as files_router
    from crabagent.serve.api.input import router as input_router
    from crabagent.serve.api.mcp_server import router as mcp_server_router
    from crabagent.serve.api.message import router as message_router
    from crabagent.serve.api.molt import router as molt_router
    from crabagent.serve.api.prompt import router as prompt_router
    from crabagent.serve.api.provider import router as provider_router
    from crabagent.serve.api.replay import router as replay_router
    from crabagent.serve.api.session import router as session_router
    from crabagent.serve.api.settings import router as settings_router
    from crabagent.serve.api.todo import router as todo_router

    app.include_router(auth_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(message_router, prefix="/api")
    app.include_router(prompt_router, prefix="/api")
    app.include_router(event_router, prefix="/api")
    app.include_router(provider_router, prefix="/api")
    app.include_router(mcp_server_router, prefix="/api")
    app.include_router(confirm_router, prefix="/api")
    app.include_router(branch_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(input_router, prefix="/api")
    app.include_router(molt_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(todo_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.3.1"}

    _mount_spa(app)

    return app


def _mount_spa(app: FastAPI):
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    dist: Path | None = None
    try:
        static_ref = importlib.resources.files("crabagent").joinpath("static")
        if static_ref.is_dir():
            dist = Path(str(static_ref))
    except Exception:
        pass

    if dist is None:
        dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
    if not dist.exists():
        logger.warning("Frontend dist not found at %s, SPA will not be served", dist)
        return

    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file = dist / full_path
        if full_path and file.exists() and file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(dist / "index.html"))
