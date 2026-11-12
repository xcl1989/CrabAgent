import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core import database as db
from crabagent.serve.api.background_tasks import router
from crabagent.serve.deps import get_current_user


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session_factory", factory)
    async with factory() as session:
        session.add_all(
            [
                db.Conversation(session_id="one", user_id=1, active_branch="main"),
                db.Conversation(session_id="two", user_id=2, active_branch="main"),
                db.BackgroundDelegation(
                    id="job",
                    user_id=1,
                    session_id="one",
                    branch_id="main",
                    agent_name="coder",
                    task="work",
                    status="succeeded",
                    result="secret",
                ),
            ]
        )
        await session.commit()

    async def database():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[db.get_db] = database
    app.dependency_overrides[get_current_user] = lambda: db.User(id=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_scope_and_result(client):
    response = await client.get("/sessions/one/background-tasks")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["branch"] == "main"
    assert "result" not in response.json()["tasks"][0]
    assert (await client.get("/sessions/one/background-tasks/job", params={"branch": "main"})).json()[
        "result"
    ] == "secret"
    assert (await client.get("/sessions/one/background-tasks/job", params={"branch": "other"})).status_code == 409
    assert (await client.get("/sessions/two/background-tasks")).status_code == 403
    assert (
        await client.post("/sessions/one/background-tasks/missing/cancel", params={"branch": "main"})
    ).status_code == 404
    assert (await client.post("/sessions/one/background-tasks/job/cancel")).status_code == 422
    assert (await client.post("/sessions/one/background-tasks/job/cancel", params={"branch": "main"})).json()[
        "status"
    ] == "succeeded"


async def test_auth_required():
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/sessions/one/background-tasks")).status_code == 401
        assert (await client.get("/sessions/one/background-tasks/groups")).status_code == 401
        assert (await client.post("/sessions/one/background-tasks/groups/g/cancel", params={"branch": "main"})).status_code == 401


async def test_group_scope_and_detail(client, monkeypatch):
    from crabagent.core.agent import background
    async def no_recovery():
        pass
    monkeypatch.setattr(background, "_recover_if_available", no_recovery)
    async with db.async_session_factory() as session:
        session.add_all([
            db.BackgroundGroup(id="group", user_id=1, session_id="one", branch_id="main", status="succeeded"),
            db.BackgroundGroup(id="hidden", user_id=1, session_id="one", branch_id="other", status="succeeded"),
            db.BackgroundGroupStep(group_id="group", step_id="step", agent_name="coder", task="work", depends_on=[], allowed_tools=[], status="succeeded", job_id="job", result="private result"),
        ])
        await session.commit()
    url = "/sessions/one/background-tasks/groups"
    listing = await client.get(url)
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    assert listing.json()["groups"] == [{"id": "group", "status": "succeeded"}]
    assert (await client.get(url + "/group", params={"branch": "main"})).json()["steps"][0]["result"] == "private result"
    assert (await client.get(url + "/hidden", params={"branch": "main"})).status_code == 404
    assert (await client.get(url + "/group", params={"branch": "other"})).status_code == 409
    assert (await client.get("/sessions/two/background-tasks/groups")).status_code == 403
    assert (await client.post(url + "/group/cancel")).status_code == 422
    assert (await client.post(url + "/hidden/cancel", params={"branch": "main"})).status_code == 404
    assert (await client.post(url + "/group/cancel", params={"branch": "main"})).json()["status"] == "succeeded"

async def test_semantic_summary_auth_and_scope(client, monkeypatch):
    from crabagent.core.agent import background, semantic_summary
    from crabagent.core.auth_utils import hash_password
    async def no_recovery():
        pass
    monkeypatch.setattr(background, "_recover_if_available", no_recovery)
    async with db.async_session_factory() as session:
        session.add_all([
            db.User(id=1, username="summary-user", password_hash=hash_password("correct-password"), enabled=True),
            db.BackgroundGroup(id="semantic", user_id=1, session_id="one", branch_id="main", status="succeeded"),
            db.BackgroundGroup(id="other-branch", user_id=1, session_id="one", branch_id="other", status="succeeded"),
        ])
        await session.commit()
    calls = []
    async def start(context, group_id, *, user_consented_to_external_processing, binding):
        calls.append((context.provider_name, context.model, user_consented_to_external_processing))
        return {"status": "pending", "text": ""}
    monkeypatch.setattr(semantic_summary, "start", start)
    url = "/sessions/one/background-tasks/groups/semantic/semantic-summary?branch=main"
    assert (await client.get(url)).json() == {"summary": None}
    assert (await client.post(url, json={"consent": False, "password": "correct-password", "binding": "test"})).status_code == 400
    assert (await client.post(url, json={"consent": "true", "password": "correct-password", "binding": "test"})).status_code == 422
    assert (await client.post(url, json={"consent": True, "password": "wrong", "binding": "test"})).status_code == 403
    assert not calls
    response = await client.post(url, json={"consent": True, "password": "correct-password", "binding": "test"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls == [("", "", True)]
    assert (await client.get(url.replace("semantic/semantic", "other-branch/semantic"))).status_code == 404
    assert (await client.get(url.replace("branch=main", "branch=other"))).status_code == 409
    assert (await client.get(url.replace("sessions/one", "sessions/two"))).status_code == 403
    assert (await client.post(url.replace("?branch", "/cancel?branch"))).json() == {"summary": None}

async def test_summary_reauthentication_limit():
    from fastapi import HTTPException
    from crabagent.serve.api.background_tasks import _attempts, _reserve_attempt
    _attempts.clear()
    for _ in range(5):
        _reserve_attempt(123)
    with pytest.raises(HTTPException) as exc:
        _reserve_attempt(123)
    assert exc.value.status_code == 429
    _attempts.clear()


async def test_delete_semantic_summary_scope_and_status(client):
    async with db.async_session_factory() as session:
        session.add_all([
            db.BackgroundGroup(id="delete-group", user_id=1, session_id="one", branch_id="main", status="succeeded"),
            db.BackgroundGroup(id="hidden-delete", user_id=1, session_id="one", branch_id="other", status="succeeded"),
            db.BackgroundSemanticSummary(group_id="delete-group", status="running", snapshot="secret", text="", run_id="run"),
        ])
        await session.commit()
    url = "/sessions/one/background-tasks/groups/delete-group/semantic-summary?branch=main"
    assert (await client.delete(url)).status_code == 409
    assert (await client.delete(url.replace("delete-group", "hidden-delete"))).status_code == 404
    assert (await client.delete(url.replace("branch=main", "branch=other"))).status_code == 409
    assert (await client.delete(url.replace("sessions/one", "sessions/two"))).status_code == 403
    async with db.async_session_factory() as session:
        row = await session.get(db.BackgroundSemanticSummary, "delete-group")
        row.status = "succeeded"
        await session.commit()
    response = await client.delete(url)
    assert response.status_code == 200 and response.json() == {"deleted": True}
    assert response.headers["cache-control"] == "no-store"
    assert (await client.delete(url)).json() == {"deleted": False}
