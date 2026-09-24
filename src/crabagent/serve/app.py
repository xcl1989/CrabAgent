from __future__ import annotations

import asyncio
import importlib.resources
import logging
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from crabagent import __version__
from crabagent.core import configure_litellm

configure_litellm()

# Log to file in crabagent config directory.
# Rotating: serve.log used to grow unbounded (>100MB) on long-lived desktop
# instances, adding disk pressure during every request write.
_log_file = Path.home() / ".crabagent" / "serve.log"
_fh = RotatingFileHandler(
    str(_log_file),
    maxBytes=20 * 1024 * 1024,
    backupCount=3,
)
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

    # Mark app as "starting" — frontend will show a loading overlay
    app.state.ready = False

    await init_db()
    logger.info("Database initialized")

    # Trusted work system: repair zombie runs and lingering tasks left by
    # a previous process. Failures must not block startup.
    try:
        from crabagent.core.database import async_session_factory
        from crabagent.core.task.recovery import recover_interrupted_state

        async with async_session_factory() as db:
            summary = await recover_interrupted_state(db)
        if any(summary.values()):
            logger.info("Startup recovery: %s", summary)
    except Exception:
        logger.exception("Startup recovery failed (non-fatal)")

    # Trusted work system: wire task domain events into the global SSE
    # queues so panels/pet/switcher refresh without polling. Events that
    # carry a session_id are also delivered to that session's stream so
    # the creating conversation can show result cards.
    def _broadcast_task_event(event_type: str, data: dict) -> None:
        import asyncio

        from crabagent.core.event import AgentEvent, EventType

        event = AgentEvent(type=EventType(event_type), data=data)
        dead_queues: list[str] = []
        for qid, (q, _ts) in list(getattr(app.state, "global_event_queues", {}).items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(qid)
        for qid in dead_queues:
            app.state.global_event_queues.pop(qid, None)

        session_id = str(data.get("session_id") or "")
        # task_created already reaches the session via the tool's own emit;
        # duplicating it here would show duplicate cards.
        if session_id and event_type == "task_updated":
            session_dead: list[str] = []
            for qid, entry in list(getattr(app.state, "event_queues", {}).items()):
                sid, critical_q, stream_q, _ts = entry
                if sid != session_id:
                    continue
                for q in (critical_q, stream_q):
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        session_dead.append(qid)
            for qid in session_dead:
                app.state.event_queues.pop(qid, None)

            # Persist terminal result cards: the chat's deferred DB-refresh
            # rebuilds the message list ~800ms after agent_end, which would
            # wipe live-only card messages. Store the card so it survives
            # refreshes and page reloads.
            if data.get("status") in ("done", "partial", "failed", "cancelled"):
                asyncio.create_task(_persist_result_card(session_id, data))

    async def _persist_result_card(session_id: str, data: dict) -> None:
        """Append (or enrich) a task_result message for the task's conversation.

        The first broadcast (often from task_done tool) may carry sparse data;
        the completion service broadcasts a richer verdict later. Instead of
        dropping duplicates on (task_id, status), upgrade the stored card when
        the new payload is richer. Failures are non-fatal — the SSE card still
        reaches open clients even if persistence fails.
        """
        try:
            import os

            from sqlalchemy import func, select

            from crabagent.core.database import (
                Conversation,
                Message,
                TaskArtifact,
                TaskCheck,
                async_session_factory,
            )

            task_id = data.get("task_id")
            if not task_id:
                return
            payload = {
                k: data.get(k)
                for k in ("task_id", "title", "status", "result_summary", "warning_summary", "verification_status")
                if data.get(k) is not None
            }
            async with async_session_factory() as db:
                conv = (
                    await db.execute(select(Conversation).where(Conversation.session_id == session_id))
                ).scalar_one_or_none()
                if not conv:
                    return

                # Enrich from execution facts: artifact files and check counts.
                artifacts = (
                    await db.execute(
                        select(TaskArtifact).where(
                            TaskArtifact.task_id == task_id,
                            TaskArtifact.status == "available",
                        )
                    )
                ).scalars().all()
                files = [a.name or os.path.basename(a.path) for a in artifacts if a.path]
                checks = (
                    await db.execute(select(TaskCheck).where(TaskCheck.task_id == task_id))
                ).scalars().all()
                required = [c for c in checks if c.required]
                payload["files"] = files
                payload["run_id"] = data.get("run_id")
                if required:
                    payload["checks"] = {
                        "passed": sum(1 for c in required if c.status == "passed"),
                        "total": len(required),
                    }
                    if payload.get("verification_status", "unverified") == "unverified":
                        if all(c.status == "passed" for c in required):
                            payload["verification_status"] = "passed"
                        elif any(c.status == "failed" for c in required):
                            payload["verification_status"] = "failed"
                        else:
                            payload["verification_status"] = "partial"

                existing_rows = (
                    await db.execute(
                        select(Message).where(
                            Message.conversation_id == conv.id,
                            Message.role == "task_result",
                            Message.compressed == False,  # noqa: E712
                        )
                    )
                ).scalars().all()
                incoming_run = payload.get("run_id") or None
                for m in existing_rows:
                    old = json_loads_safe(m.content)
                    if old.get("task_id") != task_id or old.get("status") != payload.get("status"):
                        continue
                    old_run = old.get("run_id") or None
                    # Cards with a run_id are completion episodes. Never
                    # merge them with a legacy/sparse card because that would
                    # overwrite the previous result during re-completion.
                    if incoming_run != old_run:
                        # Identical re-broadcast of an unchanged closed task
                        # (e.g. a follow-up run linked to a finished task) is
                        # not a new episode: skip instead of duplicating.
                        same_content = all(
                            old.get(k) == v
                            for k, v in payload.items()
                            if k not in ("run_id", "files", "checks")
                        )
                        if same_content:
                            return
                        continue
                    if payload != old:
                        m.content = json_dumps(payload)  # upgrade in place
                    await db.commit()
                    return  # same completion episode → never duplicate

                seq = (
                    await db.execute(
                        select(func.max(Message.sequence)).where(Message.conversation_id == conv.id)
                    )
                ).scalar()
                db.add(
                    Message(
                        conversation_id=conv.id,
                        sequence=int(seq or 0) + 1,
                        role="task_result",
                        branch_id=conv.active_branch or "main",
                        content=json_dumps(payload),
                    )
                )
                await db.commit()
        except Exception:
            logger.exception("persist task result card failed (non-fatal)")

    import json as _json

    def json_loads_safe(text: str) -> dict:
        try:
            parsed = _json.loads(text or "")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def json_dumps(payload: dict) -> str:
        return _json.dumps(payload, ensure_ascii=False)


    from crabagent.core.task.events import set_task_event_broadcaster

    set_task_event_broadcaster(_broadcast_task_event)

    monitor_task = asyncio.create_task(_loop_monitor())

    from crabagent.core.mcp.client import MCPClientManager

    manager = MCPClientManager()
    app.state.mcp_manager = manager

    # Start MCP servers in the background — don't block app startup.
    # Individual server failures are logged but never fatal.
    mcp_task = asyncio.create_task(manager.start_all())
    app.state._mcp_task = mcp_task
    logger.info("MCP servers initializing in background")

    # Non-critical services and the low-priority search catch-up are independent.
    background_init = asyncio.create_task(_background_startup(app))
    app.state._background_init = background_init
    fts_task = asyncio.create_task(_background_fts_sync(app))
    app.state._fts_task = fts_task

    # App is ready to serve API requests (init_db finished, routes mounted)
    app.state.ready = True
    logger.info("App ready — serving requests")

    yield  # ← App starts serving requests immediately

    # ── Cleanup ──

    monitor_task.cancel()

    # Wait for background init if still running
    background_init = getattr(app.state, "_background_init", None)
    if background_init and not background_init.done():
        background_init.cancel()
        try:
            await background_init
        except (asyncio.CancelledError, Exception):
            pass

    fts_task = getattr(app.state, "_fts_task", None)
    if fts_task and not fts_task.done():
        fts_task.cancel()
        try:
            await fts_task
        except (asyncio.CancelledError, Exception):
            pass

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
        from crabagent.serve.scheduler import get_scheduler

        await get_scheduler().shutdown()
    except Exception:
        pass


class InteractiveWriteTrackerMiddleware:
    """Pure ASGI middleware counting in-flight interactive write requests.

    Background maintenance (FTS indexing) reads ``state.interactive_busy`` and
    pauses between batches while user-initiated writes are in flight. Pure ASGI
    avoids BaseHTTPMiddleware, which buffers SSE streams — this app streams
    agent events over SSE.
    """

    def __init__(self, app, state_holder) -> None:
        self.next_app = app
        self.state = state_holder

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") == "http"
            and scope.get("method") in ("POST", "PUT", "PATCH", "DELETE")
            and scope.get("path", "").startswith("/api/")
        ):
            self.state.interactive_busy += 1
            try:
                await self.next_app(scope, receive, send)
            finally:
                self.state.interactive_busy -= 1
            return
        await self.next_app(scope, receive, send)


async def _background_fts_sync(app: FastAPI) -> None:
    """Start resumable search indexing after the UI and services are available."""
    try:
        # Wait for first paint + initial session/message loads before touching SQLite.
        await asyncio.sleep(10)

        def _is_busy() -> bool:
            # Active agents OR any in-flight interactive write request.
            return bool(getattr(app.state, "active_agents", None)) or getattr(app.state, "interactive_busy", 0) > 0

        from crabagent.core.fts import sync_index

        await sync_index(is_busy=_is_busy)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("FTS-CJK background sync failed (non-fatal): %s", e)


async def _background_startup(app: FastAPI) -> None:
    """Run non-critical services without waiting for search indexing."""

    # ── Scheduler startup ──
    try:
        from crabagent.serve.scheduler import get_scheduler

        sched = get_scheduler()
        sched.set_global_event_queues(app.state.global_event_queues)
        await sched.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)

    # ── OfficeCLI detection ──
    try:
        from crabagent.core.office.manager import get_office_manager

        office_mgr = get_office_manager()
        if await office_mgr.detect():
            app.state.office_available = True
            logger.info("OfficeCLI available — office tools enabled")
        else:
            app.state.office_available = False
            logger.info("OfficeCLI not found — office tools will report helpful install message")
    except Exception as e:
        logger.exception("OfficeCLI detection failed: %s", e)


def create_app() -> FastAPI:
    app = FastAPI(
        title="CrabAgent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.event_queues = {}
    app.state.global_event_queues = {}  # SSE /events/global queues
    app.state.active_agents = {}
    app.state.agent_attention = {}  # Recent completed/error states for global status consumers.
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

    # Interactive-write priority: background maintenance (FTS indexing) reads
    # this counter and pauses between batches while user-initiated writes
    # (new session, send message, updates) are in flight.
    app.state.interactive_busy = 0
    app.add_middleware(InteractiveWriteTrackerMiddleware, state_holder=app.state)

    from crabagent.serve.api.agent import router as agent_router
    from crabagent.serve.api.auth import router as auth_router
    from crabagent.serve.api.branch import router as branch_router
    from crabagent.serve.api.browser_tasks import router as browser_tasks_router
    from crabagent.serve.api.calendar import router as calendar_router
    from crabagent.serve.api.chatgpt_auth import router as chatgpt_router
    from crabagent.serve.api.confirm import router as confirm_router
    from crabagent.serve.api.documents import router as documents_router
    from crabagent.serve.api.email import router as email_router
    from crabagent.serve.api.event import router as event_router
    from crabagent.serve.api.execution import router as execution_router
    from crabagent.serve.api.files import router as files_router
    from crabagent.serve.api.goals import router as goals_router
    from crabagent.serve.api.input import router as input_router
    from crabagent.serve.api.mcp_server import router as mcp_server_router
    from crabagent.serve.api.memory import router as memory_router
    from crabagent.serve.api.message import router as message_router
    from crabagent.serve.api.molt import router as molt_router
    from crabagent.serve.api.notification import router as notification_router
    from crabagent.serve.api.officecli import router as officecli_router
    from crabagent.serve.api.pets import router as pets_router
    from crabagent.serve.api.prompt import router as prompt_router
    from crabagent.serve.api.provider import router as provider_router
    from crabagent.serve.api.quota import router as quota_router
    from crabagent.serve.api.replay import router as replay_router
    from crabagent.serve.api.scheduled_task import router as scheduled_task_router
    from crabagent.serve.api.session import router as session_router
    from crabagent.serve.api.settings import router as settings_router
    from crabagent.serve.api.task import router as task_router
    from crabagent.serve.api.task_request import router as task_request_router
    from crabagent.serve.api.todo import router as todo_router
    from crabagent.serve.api.token_usage import router as token_usage_router
    from crabagent.serve.api.wechat import router as wechat_router
    from crabagent.serve.api.work import router as work_router

    app.include_router(agent_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(browser_tasks_router, prefix="/api")
    app.include_router(goals_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(message_router, prefix="/api")
    app.include_router(prompt_router, prefix="/api")
    app.include_router(event_router, prefix="/api")
    app.include_router(provider_router, prefix="/api")
    app.include_router(quota_router, prefix="/api")
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
    app.include_router(officecli_router, prefix="/api")
    app.include_router(pets_router, prefix="/api")
    app.include_router(scheduled_task_router, prefix="/api")
    app.include_router(task_router, prefix="/api")
    app.include_router(task_request_router, prefix="/api")
    app.include_router(work_router, prefix="/api")
    app.include_router(email_router, prefix="/api")
    app.include_router(token_usage_router, prefix="/api")
    app.include_router(wechat_router, prefix="/api")
    app.include_router(chatgpt_router, prefix="/api")
    app.include_router(calendar_router, prefix="/api")
    app.include_router(execution_router, prefix="/api")

    @app.get("/health")
    async def health(request: Request):
        from crabagent.core.fts import get_rebuild_status

        fts_status = get_rebuild_status()
        return {
            "status": "ok",
            "version": __version__,
            "ready": getattr(request.app.state, "ready", True),
            "fts_rebuild": fts_status,
        }

    _mount_spa(app)

    return app


def _mount_spa(app: FastAPI):
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    dist: Path | None = None

    # 1. Try importlib.resources (works for normal pip install)
    try:
        static_ref = importlib.resources.files("crabagent").joinpath("static")
        if static_ref.is_dir():
            dist = Path(str(static_ref))
    except Exception:
        pass

    # 2. Try PyInstaller frozen location (sys._MEIPASS/_internal/static)
    if dist is None:
        try:
            import sys

            meipass = getattr(sys, "_MEIPASS", None) or (
                Path(sys.executable).parent / "_internal" if getattr(sys, "frozen", False) else None
            )
            if meipass:
                candidate = Path(meipass) / "static"
                if candidate.is_dir():
                    dist = candidate
        except Exception:
            pass

    # 3. Fallback: development path (src/crabagent/frontend/dist)
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
