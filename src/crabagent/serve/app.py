from __future__ import annotations

import asyncio
import importlib.resources
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crabagent.core import configure_litellm

configure_litellm()

# Log to file in crabagent config directory
_log_file = Path.home() / ".crabagent" / "serve.log"
_fh = logging.FileHandler(str(_log_file))
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_fh)

logger = logging.getLogger(__name__)

logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)


async def _loop_monitor():
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(1)
        delay = time.monotonic() - t0 - 1.0
        if delay > 0.5:
            logger.warning("event loop stall: %.1fms", delay * 1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from crabagent.core.database import init_db

    await init_db()
    logger.info("Database initialized")

    monitor_task = asyncio.create_task(_loop_monitor())

    from crabagent.core.mcp.client import MCPClientManager

    manager = MCPClientManager()
    app.state.mcp_manager = manager

    # Start MCP servers in the background — don't block app startup.
    # Individual server failures are logged but never fatal.
    mcp_task = asyncio.create_task(manager.start_all())
    app.state._mcp_task = mcp_task
    logger.info("MCP servers initializing in background")

    from crabagent.serve.scheduler import get_scheduler

    try:
        sched = get_scheduler()
        sched.set_global_event_queues(app.state.global_event_queues)
        await sched.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)

    # Detect OfficeCLI binary for office document tools
    from crabagent.core.office.manager import get_office_manager

    office_mgr = get_office_manager()
    if await office_mgr.detect():
        app.state.office_available = True
        logger.info("OfficeCLI available — office tools enabled")
    else:
        app.state.office_available = False
        logger.info("OfficeCLI not found — office tools will report helpful install message")

    yield

    # No explicit cleanup needed for OfficeManager

    monitor_task.cancel()

    # Wait for background MCP init to finish (if still running) before cleanup
    mcp_task = getattr(app.state, "_mcp_task", None)
    if mcp_task and not mcp_task.done():
        mcp_task.cancel()
        try:
            await mcp_task
        except (asyncio.CancelledError, Exception):
            pass

    await manager.stop_all()
    logger.info("MCP servers stopped")

    try:
        await get_scheduler().shutdown()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="CrabAgent",
        version="0.11.0",
        lifespan=lifespan,
    )
    app.state.event_queues = {}
    app.state.global_event_queues = {}  # SSE /events/global queues
    app.state.active_agents = {}
    app.state.active_sub_agents = {}

    from crabagent.core.event import EventBus

    app.state.global_event_bus = EventBus(name="global")
    logger.info("Global event bus initialized")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from crabagent.serve.api.agent import router as agent_router
    from crabagent.serve.api.auth import router as auth_router
    from crabagent.serve.api.branch import router as branch_router
    from crabagent.serve.api.calendar import router as calendar_router
    from crabagent.serve.api.confirm import router as confirm_router
    from crabagent.serve.api.documents import router as documents_router
    from crabagent.serve.api.email import router as email_router
    from crabagent.serve.api.event import router as event_router
    from crabagent.serve.api.files import router as files_router
    from crabagent.serve.api.input import router as input_router
    from crabagent.serve.api.mcp_server import router as mcp_server_router
    from crabagent.serve.api.memory import router as memory_router
    from crabagent.serve.api.message import router as message_router
    from crabagent.serve.api.molt import router as molt_router
    from crabagent.serve.api.notification import router as notification_router
    from crabagent.serve.api.prompt import router as prompt_router
    from crabagent.serve.api.provider import router as provider_router
    from crabagent.serve.api.replay import router as replay_router
    from crabagent.serve.api.scheduled_task import router as scheduled_task_router
    from crabagent.serve.api.session import router as session_router
    from crabagent.serve.api.settings import router as settings_router
    from crabagent.serve.api.task import router as task_router
    from crabagent.serve.api.todo import router as todo_router
    from crabagent.serve.api.token_usage import router as token_usage_router
    from crabagent.serve.api.wechat import router as wechat_router

    app.include_router(agent_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(message_router, prefix="/api")
    app.include_router(prompt_router, prefix="/api")
    app.include_router(event_router, prefix="/api")
    app.include_router(provider_router, prefix="/api")
    app.include_router(mcp_server_router, prefix="/api")
    app.include_router(confirm_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")
    app.include_router(branch_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(input_router, prefix="/api")
    app.include_router(molt_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(todo_router, prefix="/api")
    app.include_router(notification_router, prefix="/api")
    app.include_router(scheduled_task_router, prefix="/api")
    app.include_router(task_router, prefix="/api")
    app.include_router(email_router, prefix="/api")
    app.include_router(token_usage_router, prefix="/api")
    app.include_router(wechat_router, prefix="/api")
    app.include_router(calendar_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.11.0"}

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
