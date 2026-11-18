from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from crabagent.core.collaboration.write_coordinator import WriteConflict, file_version, replace_if_version


def test_stale_version_preserves_existing_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("first")
    version = file_version(target)
    target.write_text("external")
    with pytest.raises(WriteConflict):
        replace_if_version(target, b"candidate", version, lock_root=tmp_path / "locks")
    assert target.read_text() == "external"


def test_concurrent_writers_with_same_base_only_one_succeeds(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("base")
    version = file_version(target)
    barrier = Barrier(2)

    def write(content):
        barrier.wait()
        try:
            replace_if_version(target, content, version, lock_root=tmp_path / "locks")
            return True
        except WriteConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (b"first", b"second")))
    assert sorted(results) == [False, True]
    assert target.read_bytes() in (b"first", b"second")


def test_missing_file_is_distinct_from_empty_file(tmp_path):
    target = tmp_path / "file.txt"
    assert file_version(target) == "missing"
    replace_if_version(target, b"", "missing", lock_root=tmp_path / "locks")
    assert file_version(target) != "missing"
    with pytest.raises(WriteConflict):
        replace_if_version(target, b"new", "missing", lock_root=tmp_path / "locks")


def test_edit_refuses_change_between_read_and_commit(tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import edit

    target = tmp_path / "file.txt"
    target.write_text("original")
    real_replace = edit.replace_if_version

    def competing_write(path, content, expected_version, *, lock_root):
        target.write_text("other session")
        return real_replace(path, content, expected_version, lock_root=tmp_path / "locks")

    monkeypatch.setattr(edit, "replace_if_version", competing_write)
    result = edit.edit_file("file.txt", "original", "candidate", context=AgentContext(workspace=tmp_path))
    assert "changed during editing" in result
    assert target.read_text() == "other session"


def test_write_with_stale_read_version_does_not_overwrite(tmp_path):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.write import write_file

    target = tmp_path / "file.txt"
    target.write_text("old")
    version = file_version(target)
    target.write_text("new")
    result = write_file("file.txt", "candidate", context=AgentContext(workspace=tmp_path), expected_version=version)
    assert "changed since" in result
    assert target.read_text() == "new"


@pytest.mark.asyncio
async def test_office_manager_rejects_concurrent_modification(tmp_path, monkeypatch):
    from crabagent.core.office.manager import OfficeManager, OfficeResult

    target = tmp_path / "document.docx"
    target.write_bytes(b"old")
    manager = OfficeManager()

    async def run(cmd, timeout=60):
        from pathlib import Path

        Path(cmd[2]).write_bytes(b"candidate")
        target.write_bytes(b"new")
        return OfficeResult(success=True)

    monkeypatch.setattr(manager, "_exec_with_stdin", run)
    result = await manager._exec_guarded(["officecli", "set", str(target), "/body"], 60)
    assert not result.success
    assert "changed" in result.error
    assert target.read_bytes() == b"new"


def test_agent_read_then_write_rejects_stale_file(tmp_path):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.read import read_file
    from crabagent.core.agent.tools.write import write_file

    target = tmp_path / "test.txt"
    target.write_text("base")
    context = AgentContext(workspace=tmp_path)
    read_file("test.txt", context=context)
    target.write_text("other session")
    result = write_file("test.txt", "draft", context=context)
    assert "changed since" in result
    assert target.read_text() == "other session"


def test_agent_existing_file_requires_read_before_overwrite(tmp_path):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.write import write_file

    target = tmp_path / "test.txt"
    target.write_text("base")
    result = write_file("test.txt", "draft", context=AgentContext(workspace=tmp_path))
    assert "before overwriting" in result
    assert target.read_text() == "base"


def test_replace_preserves_executable_mode(tmp_path):
    import stat

    target = tmp_path / "run.sh"
    target.write_text("old")
    target.chmod(0o750)
    replace_if_version(target, b"new", file_version(target), lock_root=tmp_path / "locks")
    assert stat.S_IMODE(target.stat().st_mode) == 0o750


def test_coordinator_serializes_processes(tmp_path, monkeypatch):
    import multiprocessing

    from tests.collaboration_process_helper import process_write

    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "shared.txt"
    target.write_bytes(b"original")
    expected = file_version(target)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    start = ctx.Event()
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=process_write,
            args=(str(target), expected, bytes([i]), str(tmp_path / "locks"), ready, start, results),
        )
        for i in (1, 2)
    ]
    for process in processes:
        process.start()
    for _ in processes:
        assert ready.get(timeout=15) == "ready"
    start.set()
    outcomes = sorted(results.get(timeout=15) for _ in processes)
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert outcomes == ["conflict", "ok"]
    assert target.read_bytes() in (b"\x01", b"\x02")


def test_edit_refuses_external_change_since_read_even_if_old_text_remains(tmp_path):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.edit import edit_file
    from crabagent.core.agent.tools.read import read_file

    target = tmp_path / "test.txt"
    target.write_text("same text\noriginal\n")
    context = AgentContext(workspace=tmp_path)
    read_file("test.txt", context=context)
    target.write_text("same text\nexternal edit\n")
    result = edit_file("test.txt", "same text", "replacement", context=context)
    assert "changed since it was read" in result
    assert target.read_text() == "same text\nexternal edit\n"
    read_file("test.txt", context=context)
    assert edit_file("test.txt", "same text", "replacement", context=context).startswith("Successfully")


def test_observed_changes_detects_external_modification_and_deletion(tmp_path):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.read import read_file
    from crabagent.core.collaboration.observed_changes import changed_observed_files

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old")
    second.write_text("present")
    context = AgentContext(workspace=tmp_path)
    read_file("first.txt", context=context)
    read_file("second.txt", context=context)
    assert changed_observed_files(context) == []
    first.write_text("new")
    second.unlink()
    assert changed_observed_files(context) == sorted([str(first), str(second)])
    read_file("first.txt", context=context)
    assert changed_observed_files(context) == [str(second)]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_bash_tool_reports_change_to_previously_read_file(tmp_path, enabled):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.read import read_file
    from crabagent.core.agent.tools.registry import ToolRegistry

    target = tmp_path / "test.txt"
    target.write_text("before")
    context = AgentContext(workspace=tmp_path)
    context.metadata.update(_batch_molt=True, _collaboration_bound=enabled)
    read_file("test.txt", context=context)
    tools = ToolRegistry()

    @tools.register(name="bash", description="test", parameters={"type": "object", "properties": {}})
    async def shell(context=None):
        target.write_text("after")
        return "[no output]"

    result = await tools.execute("bash", {}, context=context)
    assert ("Previously read files changed" in result) == enabled
    assert (str(target) in result) == enabled
