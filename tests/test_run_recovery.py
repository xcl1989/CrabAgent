"""Tests for run-level recovery: molt linkage, changes, rollback, retry (Phase 5)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import AgentRun, Base
from crabagent.core.molt import snapshot as molt_snapshot
from crabagent.core.molt.store import create_molt
from crabagent.core.task import run_recovery
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
def workspace(tmp_path):
    (tmp_path / ".crabagent").mkdir(exist_ok=True)
    return tmp_path


def _make_molt_on_disk(workspace, molt_id: str, files: dict[str, str]):
    md = workspace / ".crabagent" / "molts" / molt_id
    for rel, content in files.items():
        dst = md / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_link_molt_to_run_is_idempotent(db):
    await create_molt(db, "molt_1", "sess", "main", "d", "copy", 1)
    await run_recovery.link_molt_to_run(db, 7, "molt_1")
    await run_recovery.link_molt_to_run(db, 7, "molt_1")

    links = await run_recovery.list_run_molts(db, 7)
    assert len(links) == 1
    assert links[0]["molt_id"] == "molt_1"


@pytest.mark.asyncio
async def test_list_run_changes_reports_modified_files(db, workspace):
    task = await task_store.add_task(db, user_id=1, title="改代码", workspace=str(workspace))
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    # pre-run snapshot: a.py had old content
    _make_molt_on_disk(workspace, "molt_a", {"a.py": "old"})
    await create_molt(db, "molt_a", "sess", "main", "before", "copy", 1, workspace=str(workspace))
    await run_recovery.link_molt_to_run(db, run_id, "molt_a")

    # current content differs
    (workspace / "a.py").write_text("new", encoding="utf-8")

    result = await run_recovery.list_run_changes(db, task["id"], run_id, 1)

    assert result["molt_count"] == 1
    assert result["changes"] == [{"file": "a.py", "molt_id": "molt_a", "status": "modified", "changed": True}]


@pytest.mark.asyncio
async def test_rollback_run_restores_pre_run_content(db, workspace):
    task = await task_store.add_task(db, user_id=1, title="改代码", workspace=str(workspace))
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    _make_molt_on_disk(workspace, "molt_a", {"a.py": "old"})
    await create_molt(db, "molt_a", "sess", "main", "before", "copy", 1, workspace=str(workspace))
    await run_recovery.link_molt_to_run(db, run_id, "molt_a")
    (workspace / "a.py").write_text("changed by run", encoding="utf-8")

    result = await run_recovery.rollback_run(db, task["id"], run_id, 1)

    assert result["status"] == "ok"
    assert result["restored"] == ["a.py"]
    assert (workspace / "a.py").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_rollback_run_removes_files_created_by_run(db, workspace):
    task = await task_store.add_task(db, user_id=1, title="生成文件", workspace=str(workspace))
    _, run_id = await task_service.start_agent_run(db, task["id"], 1)

    # empty snapshot file = file did not exist before the run
    _make_molt_on_disk(workspace, "molt_b", {"new.txt": ""})
    await create_molt(db, "molt_b", "sess", "main", "before", "copy", 1, workspace=str(workspace))
    await run_recovery.link_molt_to_run(db, run_id, "molt_b")
    (workspace / "new.txt").write_text("created by run", encoding="utf-8")

    result = await run_recovery.rollback_run(db, task["id"], run_id, 1)

    assert "new.txt" in result["restored"]
    assert not (workspace / "new.txt").exists()


@pytest.mark.asyncio
async def test_rollback_conflicts_when_later_run_touched_file(db, workspace):
    task = await task_store.add_task(db, user_id=1, title="改代码", workspace=str(workspace))
    _, run1 = await task_service.start_agent_run(db, task["id"], 1)
    await task_service.finish_agent_run(db, run1, 1, "failed", error="x")

    # run1's recovery point
    _make_molt_on_disk(workspace, "molt_1", {"a.py": "v1"})
    await create_molt(db, "molt_1", "sess", "main", "before run1", "copy", 1, workspace=str(workspace))
    await run_recovery.link_molt_to_run(db, run1, "molt_1")
    (workspace / "a.py").write_text("v2 by run1", encoding="utf-8")

    # run2 (later) also has a recovery point on the same file
    _, run2 = await task_service.start_agent_run(db, task["id"], 1)
    _make_molt_on_disk(workspace, "molt_2", {"a.py": "v2 by run1"})
    await create_molt(db, "molt_2", "sess", "main", "before run2", "copy", 1, workspace=str(workspace))
    await run_recovery.link_molt_to_run(db, run2, "molt_2")
    (workspace / "a.py").write_text("v3 by run2", encoding="utf-8")
    await task_service.finish_agent_run(db, run2, 1, "failed", error="y")

    # rolling back run1 must refuse: run2 modified the file afterwards
    result = await run_recovery.rollback_run(db, task["id"], run1, 1)

    assert result["status"] == "conflict"
    assert result["conflicts"][0]["file"] == "a.py"
    assert (workspace / "a.py").read_text(encoding="utf-8") == "v3 by run2"

    # forcing overwrites with run1's pre content
    forced = await run_recovery.rollback_run(db, task["id"], run1, 1, force=True)
    assert forced["restored"] == ["a.py"]
    assert (workspace / "a.py").read_text(encoding="utf-8") == "v1"


@pytest.mark.asyncio
async def test_retry_task_creates_new_run_and_keeps_history(db):
    task = await task_store.add_task(db, user_id=1, title="生成报告")
    _, run1 = await task_service.start_agent_run(db, task["id"], 1)
    await task_service.finish_agent_run(db, run1, 1, "failed", error="超时")

    updated, run2 = await run_recovery.retry_task(db, task["id"], 1)

    assert run2 != run1
    assert updated["status"] == "in_progress"
    assert updated["active_run_id"] == run2
    runs = await task_service.list_task_runs(db, task["id"], 1)
    assert len(runs) == 2  # history preserved


@pytest.mark.asyncio
async def test_retry_rejects_non_retryable_status(db):
    task = await task_store.add_task(db, user_id=1, title="进行中")
    await task_service.start_agent_run(db, task["id"], 1)

    with pytest.raises(ValueError, match="only failed/partial/cancelled"):
        await run_recovery.retry_task(db, task["id"], 1)


@pytest.mark.asyncio
async def test_link_active_run_molt_targets_running_run(db):
    run = AgentRun(user_id=1, agent_name="main", session_id="sess-9", status="running")
    db.add(run)
    await db.commit()
    await create_molt(db, "molt_x", "sess-9", "main", "d", "copy", 1)

    linked_run = await run_recovery.link_active_run_molt(db, "sess-9", "molt_x")

    assert linked_run == run.id
    links = await run_recovery.list_run_molts(db, run.id)
    assert links[0]["molt_id"] == "molt_x"


def test_molt_id_generator_is_unique():
    ids = {molt_snapshot._molt_id() for _ in range(100)}
    assert len(ids) == 100
