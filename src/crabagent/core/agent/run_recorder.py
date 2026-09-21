from __future__ import annotations

import logging
import time as _time

from crabagent.core.event import AgentEvent, EventType

# Tools whose successful results automatically become task artifacts.
try:
    from crabagent.core.task.artifact_service import TOOL_ARTIFACT_MAP
except Exception:  # pragma: no cover - import guard for standalone use
    TOOL_ARTIFACT_MAP = {}

logger = logging.getLogger(__name__)


class RunRecorder:
    def __init__(self, user_id: int, session_id: str, model: str = ""):
        self._user_id = user_id
        self._session_id = session_id
        self._model = model
        self._main_run_id: int | None = None
        self._main_started_at: float = 0
        self._main_tool_buf: list[dict] = []
        self._linked_task_run_ids: set[int] = set()
        self._sub_runs: dict[str, dict] = {}
        self._pipeline_run_id: int | None = None
        self._pipeline_steps: dict[str, dict] = {}

    @property
    def pipeline_run_id(self) -> int | None:
        return self._pipeline_run_id

    def link_task_run(self, run_id: int) -> None:
        """Attach a trusted-work run so its tool outputs become artifacts."""
        self._linked_task_run_ids.add(run_id)

    def unlink_task_run(self, run_id: int) -> None:
        self._linked_task_run_ids.discard(run_id)

    async def on_event(self, event: AgentEvent) -> None:
        try:
            await self._handle(event)
        except Exception:
            logger.exception("RunRecorder: failed to handle event %s", event.type)

    async def _handle(self, event: AgentEvent) -> None:
        t = event.type
        d = event.data

        if t == EventType.AGENT_START:
            await self._on_agent_start(d)
        elif t == EventType.TOOL_CALL and self._main_run_id:
            self._on_tool_call(d, self._main_tool_buf)
        elif t == EventType.TOOL_RESULT and self._main_run_id:
            entry = self._on_tool_result(d, self._main_tool_buf)
            await self._capture_artifact(d, entry, self._main_run_id)
            for run_id in tuple(self._linked_task_run_ids):
                await self._capture_artifact(d, entry, run_id)
        elif t == EventType.AGENT_END:
            await self._on_agent_end(d)
        elif t == EventType.AGENT_ERROR:
            await self._on_agent_error(d)
        elif t == EventType.BUDGET_EXHAUSTED:
            await self._on_budget_exhausted(d)
        elif t == EventType.SUB_AGENT_START:
            await self._on_sub_start(d)
        elif t == EventType.SUB_AGENT_TOOL_CALL:
            self._on_sub_tool_call(d)
        elif t == EventType.SUB_AGENT_TOOL_RESULT:
            sub_id = d.get("sub_agent_id", "")
            entry = self._sub_runs.get(sub_id)
            if entry:
                matched = self._on_tool_result(d, entry["tool_buf"])
                await self._capture_artifact(d, matched, entry.get("run_id"))
        elif t == EventType.SUB_AGENT_END:
            await self._on_sub_end(d)
        elif t == EventType.SUB_AGENT_ERROR:
            await self._on_sub_error(d)
        elif t == EventType.PIPELINE_START:
            await self._on_pipeline_start(d)
        elif t == EventType.PIPELINE_STEP_START:
            self._on_pipeline_step_start(d)
        elif t == EventType.PIPELINE_STEP_END:
            self._on_pipeline_step_end(d)
        elif t == EventType.PIPELINE_END:
            await self._on_pipeline_end(d)

    async def _on_agent_start(self, data: dict) -> None:
        from crabagent.core.database import run_record_create

        self._main_started_at = _time.time()
        self._main_tool_buf = []
        model = data.get("model") or self._model
        self._main_run_id = await run_record_create(
            user_id=self._user_id,
            agent_name="main",
            model=model,
            session_id=self._session_id,
            task_summary=data.get("query", "")[:200],
        )

    def _on_tool_call(self, data: dict, buf: list) -> None:
        buf.append(
            {
                "name": data.get("name", ""),
                "args": data.get("arguments") or data.get("args"),
                "started_at": _time.time(),
                "result_summary": None,
                "elapsed": 0,
            }
        )

    def _on_tool_result(self, data: dict, buf: list) -> dict | None:
        name = data.get("name", "")
        result = data.get("result", "")
        finished_at = _time.time()
        for tool in reversed(buf):
            if tool["name"] == name and tool["result_summary"] is None:
                tool["result_summary"] = str(result)[:500]
                tool["elapsed"] = round(finished_at - tool["started_at"], 3)
                return tool
        return None

    async def _capture_artifact(self, data: dict, entry: dict | None, run_id: int | None) -> None:
        """Auto-register task artifacts from successful file-producing tools."""
        if not run_id or not entry:
            return
        tool_name = entry.get("name", "")
        if tool_name not in TOOL_ARTIFACT_MAP:
            return
        try:
            from crabagent.core.task.artifact_service import register_artifact_from_tool

            await register_artifact_from_tool(run_id, tool_name, entry.get("args") or {}, data.get("result"))
        except Exception:
            logger.exception("RunRecorder: artifact capture failed for tool %s", tool_name)

    async def _on_agent_end(self, data: dict) -> None:
        if not self._main_run_id:
            return
        from crabagent.core.database import run_record_finalize

        elapsed = round(_time.time() - self._main_started_at, 1)
        await run_record_finalize(
            run_id=self._main_run_id,
            status="cancelled" if data.get("cancelled") else "completed",
            elapsed=elapsed,
            tokens_used=data.get("tokens", 0),
            iterations=data.get("iterations", 0),
            tool_calls=self._main_tool_buf[:] if self._main_tool_buf else None,
            result_summary=data.get("result", "")[:1000],
        )
        self._main_run_id = None
        self._main_tool_buf = []

    async def _on_agent_error(self, data: dict) -> None:
        if not self._main_run_id:
            return
        from crabagent.core.database import run_record_finalize

        elapsed = round(_time.time() - self._main_started_at, 1)
        await run_record_finalize(
            run_id=self._main_run_id,
            status="failed",
            elapsed=elapsed,
            error=str(data.get("error", ""))[:500],
        )
        self._main_run_id = None
        self._main_tool_buf = []

    async def _on_budget_exhausted(self, data: dict) -> None:
        if not self._main_run_id:
            return
        from crabagent.core.database import run_record_update

        await run_record_update(
            run_id=self._main_run_id,
            result_summary="Budget exhausted: " + str(data.get("reason", ""))[:1000],
        )

    async def _on_sub_start(self, data: dict) -> None:
        from crabagent.core.database import run_record_create

        sub_id = data.get("sub_agent_id", "")
        if not sub_id:
            return
        agent_name = data.get("agent_name", "unknown")
        model = data.get("model", "")
        pipeline_run_id = data.get("pipeline_run_id") or self._pipeline_run_id
        self._sub_runs[sub_id] = {
            "tool_buf": [],
            "started_at": _time.time(),
            "run_id": await run_record_create(
                user_id=self._user_id,
                agent_name=agent_name,
                model=model,
                session_id=data.get("session_id", self._session_id),
                parent_run_id=pipeline_run_id,
                task_summary=data.get("task", "")[:200],
                metadata={"pipeline_step_id": data.get("pipeline_step_id")} if data.get("pipeline_step_id") else None,
            ),
        }

    def _on_sub_tool_call(self, data: dict) -> None:
        sub_id = data.get("sub_agent_id", "")
        entry = self._sub_runs.get(sub_id)
        if not entry:
            return
        self._on_tool_call(data, entry["tool_buf"])

    async def _on_sub_end(self, data: dict) -> None:
        sub_id = data.get("sub_agent_id", "")
        entry = self._sub_runs.pop(sub_id, None)
        if not entry:
            return
        from crabagent.core.database import run_record_finalize

        elapsed = round(_time.time() - entry["started_at"], 1)
        await run_record_finalize(
            run_id=entry["run_id"],
            status="completed",
            elapsed=elapsed,
            tokens_used=data.get("tokens", 0),
            iterations=data.get("iterations", 0),
            tool_calls=entry["tool_buf"][:] if entry["tool_buf"] else None,
            result_summary=str(data.get("result", ""))[:1000],
        )

    async def _on_sub_error(self, data: dict) -> None:
        sub_id = data.get("sub_agent_id", "")
        entry = self._sub_runs.pop(sub_id, None)
        if not entry:
            return
        from crabagent.core.database import run_record_finalize

        elapsed = round(_time.time() - entry["started_at"], 1)
        await run_record_finalize(
            run_id=entry["run_id"],
            status="failed",
            elapsed=elapsed,
            error=str(data.get("error", ""))[:500],
        )

    async def _on_pipeline_start(self, data: dict) -> None:
        self._pipeline_steps = {}
        pipeline_run_id = data.get("pipeline_run_id")
        if pipeline_run_id:
            self._pipeline_run_id = pipeline_run_id
        else:
            from crabagent.core.database import run_record_create

            step_ids = data.get("step_ids", [])
            step_agents = data.get("step_agents", {})
            total = data.get("total_steps", len(step_ids))
            task_task = next(iter(data.get("step_tasks", {}).values()), "")
            self._pipeline_run_id = await run_record_create(
                user_id=self._user_id,
                agent_name="pipeline",
                session_id=self._session_id,
                task_summary=(task_task or f"Pipeline: {total} steps")[:200],
                metadata={"pipeline": True, "total_steps": total, "step_ids": step_ids, "step_agents": step_agents},
            )

    def _on_pipeline_step_start(self, data: dict) -> None:
        step_id = data.get("step_id", "")
        if step_id:
            started_at = data.get("started_at", _time.time())
            self._pipeline_steps[step_id] = {"started_at": started_at}

    def _on_pipeline_step_end(self, data: dict) -> None:
        step_id = data.get("step_id", "")
        if step_id in self._pipeline_steps:
            self._pipeline_steps[step_id]["done"] = True
            self._pipeline_steps[step_id]["elapsed"] = data.get("elapsed")

    async def _on_pipeline_end(self, data: dict) -> None:
        if not self._pipeline_run_id:
            return
        from crabagent.core.database import run_record_update

        total = data.get("total", 0)
        completed = data.get("completed", [])
        failed = data.get("failed", [])
        success_count = len(completed) if completed else (total - len(failed or []))
        await run_record_update(
            run_id=self._pipeline_run_id,
            status="completed" if len(failed or []) == 0 else "failed",
            result_summary=f"{success_count}/{total} steps succeeded",
        )
        self._pipeline_run_id = None
        self._pipeline_steps = {}
