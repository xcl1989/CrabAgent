"""Tests for persistent TaskRequest service (trusted work system Phase 2)."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crabagent.core.database import Base
from crabagent.core.task import request_service as rs


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_request_persists_pending_state(db):
    req = await rs.create_request(
        db,
        user_id=1,
        request_type="approval",
        title="确认发送邮件",
        operation="email_send",
        risk_level="high",
        session_id="sess-1",
        resource_version="draft-42-v3",
    )

    assert req["status"] == "pending"
    assert req["request_key"].startswith("req_")

    fetched = await rs.get_request(db, req["request_key"], 1)
    assert fetched is not None
    assert fetched["request_type"] == "approval"
    assert fetched["risk_level"] == "high"


@pytest.mark.asyncio
async def test_create_request_validates_type_and_risk(db):
    with pytest.raises(ValueError):
        await rs.create_request(db, user_id=1, request_type="upload", title="x")
    with pytest.raises(ValueError):
        await rs.create_request(db, user_id=1, request_type="input", title="x", risk_level="extreme")


@pytest.mark.asyncio
async def test_decide_approve_resolves_live_future(db):
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    req = await rs.create_request(db, user_id=1, request_type="approval", title="确认")
    rs.register_live_future(req["request_key"], future)

    payload = await rs.decide_request(db, req["request_key"], 1, "approve")

    assert payload["status"] == "approved"
    assert payload["future_resolved"] is True
    assert future.done() and future.result() is True


@pytest.mark.asyncio
async def test_decide_answer_stores_answer_in_note(db):
    req = await rs.create_request(db, user_id=1, request_type="choice", title="选择方案", options=["A", "B"])

    payload = await rs.decide_request(db, req["request_key"], 1, "answer", answer="A")

    assert payload["status"] == "approved"
    assert payload["decision_note"] == "A"


@pytest.mark.asyncio
async def test_decide_is_idempotent(db):
    req = await rs.create_request(db, user_id=1, request_type="approval", title="确认")

    first = await rs.decide_request(db, req["request_key"], 1, "approve")
    second = await rs.decide_request(db, req["request_key"], 1, "approve")

    assert first["status"] == "approved"
    assert second["status"] == "approved"
    assert second["future_resolved"] is False  # no double side effects


@pytest.mark.asyncio
async def test_decide_reject_after_approve_does_not_downgrade(db):
    req = await rs.create_request(db, user_id=1, request_type="approval", title="确认")
    await rs.decide_request(db, req["request_key"], 1, "approve")

    payload = await rs.decide_request(db, req["request_key"], 1, "reject")

    assert payload["status"] == "approved"  # recorded decision is final


@pytest.mark.asyncio
async def test_decide_expired_request_returns_expired(db):
    req = await rs.create_request(
        db,
        user_id=1,
        request_type="approval",
        title="确认",
        expires_at=datetime.datetime.now() - datetime.timedelta(seconds=1),
    )

    payload = await rs.decide_request(db, req["request_key"], 1, "approve")

    assert payload["status"] == "expired"


@pytest.mark.asyncio
async def test_decide_without_live_future_still_records(db):
    """After a restart no Future exists; the decision is still persisted."""
    req = await rs.create_request(db, user_id=1, request_type="input", title="补充信息", question="收件人？")

    payload = await rs.decide_request(db, req["request_key"], 1, "answer", answer="bob@example.com")

    assert payload["status"] == "approved"
    assert payload["future_resolved"] is False
    assert payload["decision_note"] == "bob@example.com"


@pytest.mark.asyncio
async def test_decide_missing_request_raises(db):
    with pytest.raises(LookupError):
        await rs.decide_request(db, "req_nope", 1, "approve")


@pytest.mark.asyncio
async def test_consume_request_single_shot(db):
    req = await rs.create_request(db, user_id=1, request_type="approval", title="确认")
    await rs.decide_request(db, req["request_key"], 1, "approve")

    first = await rs.consume_request(db, req["request_key"], 1)
    second = await rs.consume_request(db, req["request_key"], 1)

    assert first["status"] == "consumed"
    assert first["consumed_at"] is not None
    assert second["status"] == "consumed"  # idempotent replay


@pytest.mark.asyncio
async def test_list_pending_and_expiry_sweep(db):
    await rs.create_request(
        db,
        user_id=1,
        request_type="input",
        title="旧请求",
        expires_at=datetime.datetime.now() - datetime.timedelta(minutes=5),
    )
    await rs.create_request(db, user_id=1, request_type="input", title="新请求")

    pending = await rs.list_pending_requests(db, 1)
    assert len(pending) == 2

    expired = await rs.expire_stale_requests(db, 1)

    assert expired == 1
    pending = await rs.list_pending_requests(db, 1)
    assert [p["title"] for p in pending] == ["新请求"]
