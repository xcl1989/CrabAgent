from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base, Conversation
from crabagent.serve.api.collaboration import (
    BindingRequest,
    EntryRequest,
    ProjectRequest,
    add_entry,
    bind_session,
    create_project,
    entries,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_binding_and_handoff_isolated_by_user(db, tmp_path):
    user = SimpleNamespace(id=1)
    other = SimpleNamespace(id=2)
    db.add_all(
        [
            Conversation(session_id="a", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="b", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="other", user_id=2, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(ProjectRequest(name="project", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="a"), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="b"), user=user, db=db)
    await add_entry(project["id"], EntryRequest(session_id="a", kind="handoff", content="done"), user=user, db=db)
    result = await entries(project["id"], user=user, db=db)
    assert len(result) == 1 and result[0]["content"] == "done"
    with pytest.raises(HTTPException) as exc:
        await entries(project["id"], user=other, db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        await bind_session(project["id"], BindingRequest(session_id="other"), user=user, db=db)


@pytest.mark.asyncio
async def test_binding_rejects_different_workspace(db, tmp_path):
    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="a", user_id=1, workspace=str(tmp_path / "elsewhere")))
    await db.commit()
    project = await create_project(ProjectRequest(name="project", workspace=str(tmp_path)), user=user, db=db)
    with pytest.raises(HTTPException) as exc:
        await bind_session(project["id"], BindingRequest(session_id="a"), user=user, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_overlapping_claims_and_close(db, tmp_path):
    from crabagent.serve.api.collaboration import close_entry

    user = SimpleNamespace(id=1)
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="y", user_id=1, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session_id in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session_id), user=user, db=db)
    first = await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", content="editing", scope="src"), user=user, db=db
    )
    second = await add_entry(
        project["id"], EntryRequest(session_id="y", kind="claim", content="editing", scope="src/a.py"), user=user, db=db
    )
    assert second["overlapping_claims"] == [first["id"]]
    await close_entry(project["id"], first["id"], user=user, db=db)
    third = await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", content="other", scope="src/b.py"), user=user, db=db
    )
    assert third["overlapping_claims"] == []


@pytest.mark.asyncio
async def test_record_tool_write_requires_owned_bound_workspace(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import events
    from crabagent.serve.api.collaboration import entries

    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path)))
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)
    (tmp_path / "test.txt").write_text("changed")

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(events, "async_session_factory", DBContext)
    context = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "branch_id": "main"})
    await events.record_tool_write(context, "edit", "test.txt")
    await events.record_tool_write(context, "edit", "../outside.txt")
    result = await entries(project["id"], user=user, db=db)
    assert len(result) == 1
    assert result[0]["kind"] == "file_changed" and result[0]["scope"] == "test.txt"


@pytest.mark.asyncio
async def test_ui_write_records_only_owned_bound_session(db, tmp_path, monkeypatch):
    from crabagent.core.collaboration import events

    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path), active_branch="branch"))
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(events, "async_session_factory", DBContext)
    target = tmp_path / "doc.docx"
    target.write_bytes(b"data")
    await events.record_ui_write(2, "x", target, "office_text", "sha256:test")
    assert await entries(project["id"], user=user, db=db) == []
    await events.record_ui_write(1, "x", target, "office_text", "sha256:test")
    result = await entries(project["id"], user=user, db=db)
    assert result[0]["scope"] == "doc.docx"
    assert result[0]["branch_id"] == "branch"
    assert "sha256:test" in result[0]["content"]


@pytest.mark.asyncio
async def test_agent_claim_reports_overlap(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration

    user = SimpleNamespace(id=1)
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="y", user_id=1, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)
    await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", scope="src", content="editing"), user=user, db=db
    )

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    ctx = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    result = await collaboration.collaboration_publish("claim", "work", "src/file.py", context=ctx)
    assert "Other editing intentions" in result and "editing" in result


@pytest.mark.asyncio
async def test_session_updates_skip_own_activity_and_advance_cursor(db, tmp_path):
    from crabagent.serve.api.collaboration import session_updates

    user = SimpleNamespace(id=1)
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="y", user_id=1, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)
    other = await add_entry(
        project["id"], EntryRequest(session_id="y", kind="handoff", content="done"), user=user, db=db
    )
    own = await add_entry(project["id"], EntryRequest(session_id="x", kind="claim", content="mine"), user=user, db=db)
    response = await session_updates("x", user=user, db=db)
    assert [entry["id"] for entry in response["entries"]] == [other["id"]]
    assert response["cursor"] == own["id"]
    empty = await session_updates("x", after=response["cursor"], user=user, db=db)
    assert empty["entries"] == [] and empty["cursor"] == own["id"]
    with pytest.raises(HTTPException):
        await session_updates("x", user=SimpleNamespace(id=2), db=db)


@pytest.mark.asyncio
async def test_competing_claims_excludes_current_branch(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import claims

    user = SimpleNamespace(id=1)
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(tmp_path)),
            Conversation(session_id="y", user_id=1, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)
    await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", scope="src", content="mine"), user=user, db=db
    )
    await add_entry(
        project["id"], EntryRequest(session_id="y", kind="claim", scope="src", content="theirs"), user=user, db=db
    )

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    import crabagent.core.database as database

    monkeypatch.setattr(database, "async_session_factory", DBContext)
    ctx = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "branch_id": "main"})
    matches = await claims.competing_claims(ctx, "src/file.py")
    assert len(matches) == 1 and matches[0]["session"] == "y"


@pytest.mark.asyncio
async def test_unbinding_closes_active_claims(db, tmp_path):
    from crabagent.serve.api.collaboration import unbind_session

    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path)))
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)
    await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", scope="src", content="work"), user=user, db=db
    )
    await unbind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)
    records = await entries(project["id"], user=user, db=db)
    assert records[0]["state"] == "closed"


@pytest.mark.asyncio
async def test_bound_document_edit_requires_real_version(db, tmp_path, monkeypatch):
    import crabagent.core.database as database
    from crabagent.serve.api import documents

    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path)))
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(database, "async_session_factory", DBContext)
    with pytest.raises(HTTPException) as exc:
        await documents._require_bound_session_version(1, "x", "")
    assert exc.value.status_code == 428
    await documents._require_bound_session_version(1, "x", "sha256:valid")
    await documents._require_bound_session_version(2, "x", "")


@pytest.mark.asyncio
async def test_external_changes_are_detected_within_owned_project(db, tmp_path):
    from crabagent.core.collaboration.write_coordinator import file_version
    from crabagent.serve.api.collaboration import VersionCheckRequest, VersionItem, check_versions

    user = SimpleNamespace(id=1)
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    target = tmp_path / "doc.txt"
    target.write_text("old")
    version = file_version(target)
    target.write_text("external edit")
    req = VersionCheckRequest(files=[VersionItem(path="doc.txt", version=version)])
    result = await check_versions(project["id"], req, user=user, db=db)
    assert result["files"][0]["changed"] is True
    assert result["guarantee"] == "observation_only"
    with pytest.raises(HTTPException):
        await check_versions(project["id"], req, user=SimpleNamespace(id=2), db=db)
    for path in ("../outside", str(target)):
        with pytest.raises(HTTPException):
            await check_versions(
                project["id"], VersionCheckRequest(files=[VersionItem(path=path, version="missing")]), user=user, db=db
            )


@pytest.mark.asyncio
async def test_external_version_check_refuses_symlink_escape(db, tmp_path):
    from crabagent.serve.api.collaboration import VersionCheckRequest, VersionItem, check_versions

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("private")
    (workspace / "link").symlink_to(outside)
    user = SimpleNamespace(id=1)
    project = await create_project(ProjectRequest(name="p", workspace=str(workspace)), user=user, db=db)
    with pytest.raises(HTTPException):
        await check_versions(
            project["id"], VersionCheckRequest(files=[VersionItem(path="link", version="missing")]), user=user, db=db
        )


@pytest.mark.asyncio
async def test_agent_can_only_close_own_branch_claim(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.database import CollaborationEntry

    user = SimpleNamespace(id=1)
    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path)))
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    await bind_session(project["id"], BindingRequest(session_id="x"), user=user, db=db)
    records = [
        CollaborationEntry(
            user_id=1, project_id=project["id"], session_id="x", branch_id="main", kind="claim", content="own"
        ),
        CollaborationEntry(
            user_id=1, project_id=project["id"], session_id="x", branch_id="other", kind="claim", content="branch"
        ),
        CollaborationEntry(
            user_id=1, project_id=project["id"], session_id="other", branch_id="main", kind="claim", content="session"
        ),
        CollaborationEntry(
            user_id=1, project_id=project["id"], session_id="x", branch_id="main", kind="handoff", content="handoff"
        ),
    ]
    db.add_all(records)
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    context = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "branch_id": "main"})
    for record in records[1:]:
        assert "not found" in await collaboration.collaboration_close_claim(record.id, context=context)
    assert await collaboration.collaboration_close_claim(records[0].id, context=context) == "Claim closed."
    assert "not found" in await collaboration.collaboration_close_claim(records[0].id, context=context)
    assert [record.state for record in records] == ["closed", "active", "active", "active"]


@pytest.mark.asyncio
async def test_automatic_claim_blocks_overlap_and_releases(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims

    user = SimpleNamespace(id=1)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    # The production factory supplies a fresh session for each transaction.
    await db.rollback()
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "_collaboration_bound": True})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y", "_collaboration_bound": True})
    claim, error = await automatic_claims.acquire(x, "src/a.py")
    assert claim and not error
    blocked, error = await automatic_claims.acquire(y, "src/a.py")
    assert blocked is None and "claimed" in error
    await automatic_claims.finish(x, claim, True, "write")
    claim2, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim2 and not error
    result = await entries(project["id"], user=user, db=db)
    assert any(e["kind"] == "handoff" and e["scope"] == "src/a.py" for e in result)


@pytest.mark.asyncio
async def test_automatic_claim_discovers_other_git_project(db, tmp_path, monkeypatch):
    from sqlalchemy import select

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationProject

    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        directory.mkdir()
        (directory / ".git").mkdir()
    db.add(Conversation(session_id="x", user_id=1, workspace=str(first)))
    await db.commit()
    project = await create_project(
        ProjectRequest(name="first", workspace=str(first)), user=SimpleNamespace(id=1), db=db
    )
    await bind_session(project["id"], BindingRequest(session_id="x"), user=SimpleNamespace(id=1), db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    context = AgentContext(workspace=first, metadata={"user_id": 1, "session_id": "x"})
    claim, error = await automatic_claims.acquire(context, str(second / "file.py"))
    assert claim and error is None
    await automatic_claims.finish(context, claim, True, "write")
    projects = (await db.execute(select(CollaborationProject))).scalars().all()
    assert {p.workspace for p in projects} == {str(first), str(second)}
    other = next(p for p in projects if p.workspace == str(second))
    result = await entries(other.id, user=SimpleNamespace(id=1), db=db)
    assert any(e["kind"] == "handoff" and e["scope"] == "file.py" for e in result)


@pytest.mark.asyncio
async def test_standalone_file_cooperates_across_workspaces(db, tmp_path, monkeypatch):
    from sqlalchemy import select

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationProject

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(first)),
            Conversation(session_id="y", user_id=1, workspace=str(second)),
        ]
    )
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=first, metadata={"user_id": 1, "session_id": "x"})
    y = AgentContext(workspace=second, metadata={"user_id": 1, "session_id": "y"})
    target = tmp_path / "independent.docx"
    claim, error = await automatic_claims.acquire(x, str(target))
    assert claim and not error
    other, error = await automatic_claims.acquire(y, str(target))
    assert other is None and "claimed" in error
    unrelated, error = await automatic_claims.acquire(y, str(tmp_path / "other.docx"))
    assert unrelated and not error
    await automatic_claims.finish(x, claim, True, "office_edit")
    other, error = await automatic_claims.acquire(y, str(target))
    assert other and not error
    projects = (await db.execute(select(CollaborationProject))).scalars().all()
    assert {p.workspace for p in projects} == {str(target), str(tmp_path / "other.docx")}


@pytest.mark.asyncio
async def test_standalone_claim_overlaps_bound_workspace_claim(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db.add_all(
        [
            Conversation(session_id="x", user_id=1, workspace=str(workspace)),
            Conversation(session_id="y", user_id=1, workspace=str(tmp_path)),
        ]
    )
    await db.commit()
    project = await create_project(
        ProjectRequest(name="p", workspace=str(workspace)), user=SimpleNamespace(id=1), db=db
    )
    await bind_session(project["id"], BindingRequest(session_id="x"), user=SimpleNamespace(id=1), db=db)
    await add_entry(
        project["id"],
        EntryRequest(session_id="x", kind="claim", scope="folder", content="editing"),
        user=SimpleNamespace(id=1),
        db=db,
    )

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    context = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    claim, error = await automatic_claims.acquire(context, str(workspace / "folder" / "new.txt"))
    assert claim is None and "claimed" in error


@pytest.mark.asyncio
async def test_abandoned_automatic_claim_recovers_without_releasing_live_claim(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationEntry

    monkeypatch.setattr(automatic_claims.Path, "home", lambda: tmp_path)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x"})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    claim, _ = await automatic_claims.acquire(x, "file.txt")
    _, error = await automatic_claims.acquire(y, "file.txt")
    assert "claimed" in error
    automatic_claims._release_lock(claim)
    replacement, error = await automatic_claims.acquire(y, "file.txt")
    assert replacement and error is None
    assert (await db.get(CollaborationEntry, claim)).state == "closed"
    await automatic_claims.finish(y, replacement, False, "write")


@pytest.mark.asyncio
async def test_status_includes_touched_projects_but_not_other_users(db, tmp_path, monkeypatch):
    import json

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.database import CollaborationEntry, CollaborationProject

    db.add(Conversation(session_id="x", user_id=1, workspace=str(tmp_path)))
    db.add_all(
        [
            CollaborationProject(id=1, user_id=1, name="one", workspace="/one"),
            CollaborationProject(id=2, user_id=1, name="two", workspace="/two"),
            CollaborationProject(id=3, user_id=2, name="private", workspace="/private"),
        ]
    )
    db.add_all(
        [
            CollaborationEntry(user_id=1, project_id=1, session_id="x", kind="handoff", content="own"),
            CollaborationEntry(user_id=1, project_id=1, session_id="y", kind="handoff", content="peer"),
            CollaborationEntry(user_id=1, project_id=2, session_id="x", kind="handoff", content="second"),
            CollaborationEntry(user_id=2, project_id=3, session_id="x", kind="handoff", content="private"),
        ]
    )
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    context = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x"})
    records = json.loads(await collaboration.collaboration_status(context=context))
    assert {item["content"] for item in records} == {"own", "peer", "second"}
    assert {item["workspace"] for item in records} == {"/one", "/two"}


def test_abandoned_claim_lock_detects_real_process_exit(tmp_path):
    import os
    import subprocess
    import sys

    from crabagent.core.collaboration import automatic_claims

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    script = (
        "from crabagent.core.collaboration.automatic_claims import _new_lock; "
        "import sys; token, fd, path = _new_lock(); "
        "print(token, flush=True); sys.stdin.readline()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )
    try:
        token = process.stdout.readline().strip()
        assert len(token) == 32
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            assert not automatic_claims._stale_lock(token)
            process.kill()
            process.wait(timeout=10)
            assert automatic_claims._stale_lock(token)
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()


@pytest.mark.asyncio
async def test_directory_claim_conflicts_with_files_and_other_directory(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims

    (tmp_path / ".git").mkdir()
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x"})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    claim, error = await automatic_claims.acquire(x, str(tmp_path))
    assert claim and not error
    for path in (tmp_path / "src" / "main.py", tmp_path):
        blocked, error = await automatic_claims.acquire(y, str(path))
        assert blocked is None and "claimed" in error
    await automatic_claims.finish(x, claim, False, "bash")
    claim, error = await automatic_claims.acquire(y, str(tmp_path / "src" / "main.py"))
    assert claim and not error
    blocked, error = await automatic_claims.acquire(x, str(tmp_path))
    assert blocked is None and "claimed" in error
    await automatic_claims.finish(y, claim, False, "write")


@pytest.mark.asyncio
async def test_bash_remains_usable_when_workspace_claimed(db, tmp_path, monkeypatch):
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools.registry import ToolRegistry
    from crabagent.core.collaboration import automatic_claims

    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=SimpleNamespace(id=1), db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=SimpleNamespace(id=1), db=db)
    await add_entry(
        project["id"],
        EntryRequest(session_id="x", kind="claim", scope=".", content="busy"),
        user=SimpleNamespace(id=1),
        db=db,
    )

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    tools = ToolRegistry()

    @tools.register(name="bash", description="test", parameters={"type": "object", "properties": {}})
    async def shell(workdir=None, context=None):
        return "done"

    context = AgentContext(
        workspace=tmp_path,
        metadata={"user_id": 1, "session_id": "y", "_collaboration_bound": True, "_batch_molt": True},
    )
    assert await tools.execute("bash", {"workdir": str(tmp_path)}, context=context) == "done"
    claim, error = await automatic_claims.acquire(context, str(tmp_path / "file.txt"))
    assert claim is None and "claimed" in error


@pytest.mark.asyncio
async def test_background_claim_remains_after_owner_process_exits(db, tmp_path, monkeypatch):
    import asyncio
    import os
    import sys

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationEntry

    monkeypatch.setattr(automatic_claims.Path, "home", lambda: tmp_path)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x"})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    try:
        claim, _ = await automatic_claims.acquire(x, "file.txt")
        automatic_claims.persist_background_pid(claim, process.pid)
        fd, path = automatic_claims._LOCKS.pop(claim)
        os.close(fd)  # Simulate server death: the marker survives, the OS lock does not.
        blocked, error = await automatic_claims.acquire(y, "file.txt")
        assert blocked is None and "claimed" in error
        process.terminate()
        await process.wait()
        replacement, error = await automatic_claims.acquire(y, "file.txt")
        assert replacement and not error
        assert (await db.get(CollaborationEntry, claim)).state == "closed"
        await automatic_claims.finish(y, replacement, False, "write")
        path.unlink(missing_ok=True)
        path.with_suffix(".pid").unlink(missing_ok=True)
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


@pytest.mark.asyncio
async def test_batch_intentions_allow_overlap_and_finish_own_only(db, tmp_path, monkeypatch):
    import json

    from sqlalchemy import select

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationEntry

    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    user = SimpleNamespace(id=1)
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "branch_id": "main"})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y", "branch_id": "main"})
    data = json.loads(await collaboration.collaboration_claim_batch(["src", "tests"], "work", context=x))
    assert len(data["claim_ids"]) == 2
    claim, error = await automatic_claims.acquire(x, str(tmp_path / "src" / "file.py"))
    assert claim is None and error is None
    concurrent = json.loads(await collaboration.collaboration_claim_batch(["other", "src/file.py"], "parallel", context=y))
    assert len(concurrent["claim_ids"]) == 2
    assert [item["id"] for item in concurrent["overlapping_intentions"]] == data["claim_ids"][:1]
    rows = (await db.execute(select(CollaborationEntry))).scalars().all()
    assert len(rows) == 4
    result = await collaboration.collaboration_finish_batch(data["claim_ids"], "finished", context=y)
    assert "nothing changed" in result
    rows = (await db.execute(select(CollaborationEntry))).scalars().all()
    assert all(e.state == "active" for e in rows)
    await db.rollback()
    result = json.loads(await collaboration.collaboration_finish_batch(data["claim_ids"], "finished", context=x))
    assert result["closed"] == data["claim_ids"]
    rows = (await db.execute(select(CollaborationEntry))).scalars().all()
    assert [e.state for e in rows[:2]] == ["closed", "closed"]
    assert len(rows) == 5 and rows[-1].kind == "handoff"
    assert all(e.state == "active" for e in rows[2:4])


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_run_releases_only_its_batch_claims(db, tmp_path, monkeypatch, outcome):
    import asyncio
    import json

    from sqlalchemy import select

    from crabagent.core.agent import loop
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.database import CollaborationEntry

    user = SimpleNamespace(id=1)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)
    previous = await add_entry(
        project["id"], EntryRequest(session_id="x", kind="claim", scope="old", content="old"), user=user, db=db
    )
    other = await add_entry(
        project["id"], EntryRequest(session_id="y", kind="claim", scope="other", content="other"), user=user, db=db
    )

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    context = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "branch_id": "main"})
    created = []

    async def execute(ctx, query):
        result = json.loads(await collaboration.collaboration_claim_batch(["src", "tests"], "working", context=ctx))
        created.extend(result["claim_ids"])
        if outcome == "failure":
            raise RuntimeError("failed")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return []

    monkeypatch.setattr(loop, "_run_agent", execute)
    if outcome == "success":
        assert await loop.run_agent(context, "test") == []
    elif outcome == "failure":
        with pytest.raises(RuntimeError):
            await loop.run_agent(context, "test")
    else:
        with pytest.raises(asyncio.CancelledError):
            await loop.run_agent(context, "test")
    rows = (await db.execute(select(CollaborationEntry).order_by(CollaborationEntry.id))).scalars().all()
    assert {e.id: e.state for e in rows} == {
        previous["id"]: "active",
        other["id"]: "active",
        **{i: "closed" for i in created},
    }
    assert all(e.kind == "claim" for e in rows)


@pytest.mark.asyncio
async def test_batch_claim_recovered_after_run_lease_lost(db, tmp_path, monkeypatch):
    import json
    import os

    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.collaboration import automatic_claims

    user = SimpleNamespace(id=1)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "_run_batch_claim_ids": []})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})
    result = json.loads(await collaboration.collaboration_claim_batch(["src"], "work", context=x))
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim is None and "claimed" in error
    lease = x.metadata.pop("_run_batch_lease")
    os.close(lease[1])
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim and not error
    assert result["claim_ids"] == x.metadata["_run_batch_claim_ids"]
    await automatic_claims.finish(y, claim, False, "write")
    lease[2].unlink(missing_ok=True)


def test_batch_lease_survives_until_real_process_exit(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    from crabagent.core.collaboration.automatic_claims import stale_run_batch_claim

    monkeypatch.setenv("HOME", str(tmp_path))
    env = os.environ.copy()
    script = (
        "from crabagent.core.collaboration.automatic_claims import _new_lock; "
        "import sys; token, fd, path = _new_lock(); "
        "print(token, flush=True); sys.stdin.readline()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )
    try:
        token = process.stdout.readline().strip()
        assert len(token) == 32
        content = f"Run batch claim: {token}\nwork"
        assert not stale_run_batch_claim(content)
        process.kill()
        process.wait(timeout=10)
        assert stale_run_batch_claim(content)
        assert not stale_run_batch_claim("Run batch claim: invalid\nwork")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()


@pytest.mark.asyncio
async def test_lease_cleanup_error_does_not_hide_run_result_or_skip_browser_release(tmp_path, monkeypatch):
    from crabagent.core.agent import loop
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration_browser

    calls = []

    class BadPath:
        def unlink(self, missing_ok=False):
            raise OSError("cannot unlink")

    async def run(context, query):
        context.metadata["_run_batch_lease"] = ("token", -1, BadPath())
        context.metadata["_collab_browser_used"] = True
        return [{"role": "assistant", "content": "done"}]

    monkeypatch.setattr(loop, "_run_agent", run)
    monkeypatch.setattr(collaboration_browser, "_bridge_request", lambda command, context: calls.append(command))
    result = await loop.run_agent(AgentContext(workspace=tmp_path), "test")
    assert result == [{"role": "assistant", "content": "done"}]
    assert calls == ["release"]


@pytest.mark.asyncio
async def test_goal_batch_claim_survives_turn_pause_and_releases_on_close(db, tmp_path, monkeypatch):
    import json

    from sqlalchemy import select

    from crabagent.core.agent import loop
    from crabagent.core.agent.context import AgentContext
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.collaboration import automatic_claims
    from crabagent.core.database import CollaborationEntry, Goal
    from crabagent.core.goals.service import update_goal

    user = SimpleNamespace(id=1)
    db.add_all([Conversation(session_id=s, user_id=1, workspace=str(tmp_path)) for s in ("x", "y")])
    await db.commit()
    project = await create_project(ProjectRequest(name="p", workspace=str(tmp_path)), user=user, db=db)
    for session in ("x", "y"):
        await bind_session(project["id"], BindingRequest(session_id=session), user=user, db=db)
    goal = Goal(user_id=1, session_id="x", objective="build", status="active")
    db.add(goal)
    await db.commit()
    goal_id = goal.id

    class DBContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(collaboration, "async_session_factory", DBContext)
    monkeypatch.setattr(automatic_claims, "async_session_factory", DBContext)
    x = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "x", "goal_id": goal_id})
    y = AgentContext(workspace=tmp_path, metadata={"user_id": 1, "session_id": "y"})

    async def execute(ctx, query):
        result = json.loads(await collaboration.collaboration_claim_batch(["src", "tests"], "working", context=ctx))
        assert len(result["claim_ids"]) == 2
        return []

    monkeypatch.setattr(loop, "_run_agent", execute)
    await loop.run_agent(x, "turn one")
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim is None and "claimed" in error
    goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    await update_goal(db, goal, status="paused")
    await db.commit()
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim is None and "claimed" in error
    goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    await update_goal(db, goal, status="complete", evidence="tests passed")
    await db.rollback()
    goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    assert goal.status == "paused"
    await db.rollback()
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim is None and "claimed" in error
    goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    await update_goal(db, goal, status="complete", evidence="tests passed")
    await db.commit()
    claim, error = await automatic_claims.acquire(y, "src/a.py")
    assert claim and error is None
    await automatic_claims.finish(y, claim, False, "write")
    rows = (await db.execute(select(CollaborationEntry).where(CollaborationEntry.session_id == "x"))).scalars().all()
    assert len(rows) == 2 and all(row.state == "closed" for row in rows)
