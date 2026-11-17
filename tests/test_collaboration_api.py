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
    assert "Overlapping active claims" in result


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
