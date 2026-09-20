"""Tests for artifact capture + verification + completion judgment (Phase 3)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.task import artifact_service as artifacts
from crabagent.core.task import completion
from crabagent.core.task import service as task_service
from crabagent.core.task import store as task_store


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def report_file(tmp_path):
    f = tmp_path / "report.docx"
    f.write_bytes(b"PK\x03\x04 fake docx content")
    return str(f)


# ── artifact service ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_artifact_records_available_file(db, report_file):
    task = await task_store.add_task(db, user_id=1, title="写报告")

    art = await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=None,
        artifact_type="file",
        name="report.docx",
        path=report_file,
        action="created",
    )

    assert art["status"] == "available"
    assert art["version"] == 1
    listed = await artifacts.list_artifacts(db, task["id"], 1)
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_register_same_path_supersedes_and_bumps_version(db, report_file):
    task = await task_store.add_task(db, user_id=1, title="写报告")
    await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=None,
        artifact_type="file",
        name="report.docx",
        path=report_file,
        action="created",
    )

    updated = await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=None,
        artifact_type="file",
        name="report.docx",
        path=report_file,
        action="modified",
    )

    assert updated["version"] == 2
    listed = await artifacts.list_artifacts(db, task["id"], 1)
    assert len(listed) == 2
    assert {a["status"] for a in listed} == {"superseded", "available"}
    assert await artifacts.current_artifact_version(db, task["id"], report_file) == 2


@pytest.mark.asyncio
async def test_register_missing_file_marks_missing(db):
    task = await task_store.add_task(db, user_id=1, title="写报告")

    art = await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=None,
        artifact_type="file",
        name="ghost.txt",
        path="/nonexistent/ghost.txt",
        action="created",
    )

    assert art["status"] == "missing"


def test_extract_tool_paths_write_and_image():
    paths = artifacts.extract_tool_paths("write", {"file_path": "/tmp/a.md"}, "ok")
    assert paths == [("/tmp/a.md", "a.md")]

    result = json.dumps({"files": ["/tmp/img1.png", "/tmp/img2.png"]})
    paths = artifacts.extract_tool_paths("image_generate", {}, result)
    assert [p for p, _ in paths] == ["/tmp/img1.png", "/tmp/img2.png"]

    assert artifacts.extract_tool_paths("bash", {"command": "ls"}, "") == []


def test_tool_result_failed_detection():
    assert artifacts.tool_result_failed("创建失败: 磁盘满") is True
    assert artifacts.tool_result_failed("File not found: /tmp/x") is True
    assert artifacts.tool_result_failed("✅ 文档已创建: /tmp/a.docx") is False


@pytest.mark.asyncio
async def test_register_from_tool_skips_run_without_task(monkeypatch):
    # register_artifact_from_tool uses the global session factory.
    import crabagent.core.database as database

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", factory)

    # No AgentRun with id 999 → None, no crash.
    assert await artifacts.register_artifact_from_tool(999, "write", {"file_path": "/x"}, "ok") is None
    await engine.dispose()


# ── verification ────────────────────────────────────────────────────


def test_verify_file_passes_real_file(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("hello")

    outcome = completion.verify_file(str(f))

    assert outcome["status"] == "passed"
    assert "可读取" in outcome["evidence"]


def test_verify_file_missing_fails():
    outcome = completion.verify_file("/nonexistent/x.txt")

    assert outcome["status"] == "failed"


def test_verify_file_empty_warns(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")

    outcome = completion.verify_file(str(f))

    assert outcome["status"] == "warning"
    assert "文件为空" in outcome["evidence"]


def test_verify_file_workspace_boundary(tmp_path):
    inside = tmp_path / "in.txt"
    inside.write_text("x")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x")

    assert completion.verify_file(str(inside), workspace=str(tmp_path))["status"] == "passed"
    outcome = completion.verify_file(str(outside), workspace=str(tmp_path))
    assert "边界之外" in outcome["evidence"]
    outside.unlink()


# ── completion judgment ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finish_run_with_verified_artifact_judges_done(db, report_file):
    task = await task_store.add_task(db, user_id=1, title="写报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)
    await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=run_id,
        artifact_type="file",
        name="report.docx",
        path=report_file,
        action="created",
    )

    updated = await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="报告完成")

    assert updated["status"] == "done"
    assert updated["verification_status"] == "passed"
    assert updated["completed_at"] is not None
    assert updated["active_run_id"] is None


@pytest.mark.asyncio
async def test_finish_run_with_missing_artifact_judges_partial(db):
    task = await task_store.add_task(db, user_id=1, title="写报告")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)
    await artifacts.register_artifact(
        db,
        user_id=1,
        task_id=task["id"],
        run_id=run_id,
        artifact_type="file",
        name="ghost.txt",
        path="/nonexistent/ghost.txt",
        action="created",
    )

    updated = await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="完成")

    assert updated["status"] == "partial"
    assert updated["verification_status"] == "failed"


@pytest.mark.asyncio
async def test_finish_run_without_artifact_or_summary_judges_failed(db):
    task = await task_store.add_task(db, user_id=1, title="查资料")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    updated = await task_service.finish_agent_run(db, run_id, 1, "completed")

    assert updated["status"] == "failed"


@pytest.mark.asyncio
async def test_finish_run_summary_only_judges_done(db):
    task = await task_store.add_task(db, user_id=1, title="回答问题")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    updated = await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="答案：42")

    assert updated["status"] == "done"
    assert updated["verification_status"] == "unverified"  # no checks → unverified


@pytest.mark.asyncio
async def test_pending_request_makes_task_waiting_user(db):
    from crabagent.core.task import request_service as rs

    task = await task_store.add_task(db, user_id=1, title="发邮件")
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)
    await rs.create_request(
        db,
        user_id=1,
        request_type="approval",
        title="确认发送",
        task_id=task["id"],
        run_id=run_id,
    )

    updated = await task_service.finish_agent_run(db, run_id, 1, "completed", result_summary="草稿已备好")

    assert updated["status"] == "waiting_user"
