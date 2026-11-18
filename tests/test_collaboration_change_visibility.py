from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.agent.context import AgentContext
from crabagent.core.agent.tools.edit import edit_file
from crabagent.core.collaboration import events
from crabagent.core.database import Base, CollaborationBinding, CollaborationProject
from crabagent.serve.api.collaboration import entries


@pytest.mark.asyncio
async def test_parallel_read_edit_and_diff_preserve_both_changes(tmp_path, monkeypatch):
    from crabagent.core.agent.tools import collaboration
    from crabagent.core.agent.tools.registry import registry
    from crabagent.core.database import Conversation
    from crabagent.core.event import EventType
    from crabagent.serve.api.collaboration import file_activity

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            project = CollaborationProject(user_id=1, workspace=str(tmp_path), name="test")
            db.add(project)
            await db.flush()
            for session in ("a", "b"):
                db.add(Conversation(session_id=session, user_id=1, workspace=str(tmp_path)))
                db.add(CollaborationBinding(session_id=session, user_id=1, project_id=project.id))
            await db.commit()
            project_id = project.id
        monkeypatch.setattr(events, "async_session_factory", factory)
        monkeypatch.setattr(collaboration, "async_session_factory", factory)
        path = tmp_path / "sample.txt"
        path.write_text("alpha before\nbeta before\n")

        def context(session, branch="main"):
            return AgentContext(
                workspace=tmp_path,
                metadata={
                    "user_id": 1,
                    "session_id": session,
                    "branch_id": branch,
                    "_collaboration_bound": True,
                    "_batch_molt": True,
                },
            )

        async def read(ctx):
            return await registry.execute("read", {"file_path": str(path)}, ctx)

        async def edit(ctx, old, new):
            return await registry.execute("edit", {"file_path": str(path), "old_string": old, "new_string": new}, ctx)

        a, b = context("a"), context("b")
        assert "Published" in await collaboration.collaboration_publish("claim", "Updating alpha", "sample.txt", a)
        notice = await read(b)
        assert "Updating alpha" in notice and "not locks" in notice
        assert "Updating alpha" not in await read(b)
        assert "Updating alpha" not in await read(a)
        assert "Updating alpha" in await read(context("a", "alternate"))
        async with factory() as db:
            visible = await file_activity("b", str(path), user=SimpleNamespace(id=1), db=db)
            assert visible["intentions"][0]["summary"] == "Updating alpha"
            assert not visible["changes"]
        assert (await edit(a, "alpha before", "alpha after")).startswith("Successfully")
        assert path.read_text() == "alpha after\nbeta before\n"
        c = context("b")
        emitted = []

        async def record(event):
            if event.type == EventType.COLLABORATION_ACTIVITY:
                emitted.append((event.data["message"], path.read_text()))

        c.event_bus.subscribe(record)
        assert "before editing" in await edit(c, "beta before", "beta after")
        assert emitted and "Updating alpha" in emitted[0][0]
        assert "beta before" in emitted[0][1]
        stale = await edit(b, "beta before", "beta after")
        assert "changed since it was read" in stale and "+alpha after" in stale
        assert "alpha after" in await read(b)
        assert (await edit(b, "beta before", "beta after")).startswith("Successfully")
        assert path.read_text() == "alpha after\nbeta after\n"
        async with factory() as db:
            result = await entries(project_id, user=SimpleNamespace(id=1), db=db)
        assert any("+alpha after" in row["content"] for row in result)
        assert any("+beta after" in row["content"] for row in result)
        detail = await collaboration.collaboration_status(file_path="sample.txt", context=b)
        assert "+alpha after" in detail
        assert "inside the current workspace" in await collaboration.collaboration_status(
            file_path="../outside",
            context=b,
        )
    finally:
        await engine.dispose()


def test_stale_edit_does_not_overwrite(tmp_path):
    from crabagent.core.agent.tools.read import read_file

    path = tmp_path / "sample.txt"
    path.write_text("before\n")
    context = AgentContext(workspace=tmp_path)
    read_file(str(path), context=context)
    path.write_text("changed elsewhere\n")
    assert "changed since it was read" in edit_file(str(path), "before", "after", context)
    assert path.read_text() == "changed elsewhere\n"
