from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from crabagent.core.computer import audit
from crabagent.serve.api.browser_tasks import CreateBrowserTaskEventRequest


def test_client_event_rejects_sensitive_metadata():
    for data in ({"text": "secret"}, {"tool": "https://user:password@example.com/"}):
        with pytest.raises(ValidationError):
            CreateBrowserTaskEventRequest(event_type="tool_result", detail="computer_act", data=data)
    with pytest.raises(ValidationError):
        CreateBrowserTaskEventRequest(event_type="action_result", detail="computer_act")
    assert CreateBrowserTaskEventRequest(event_type="tool_result", detail="computer_act", data={"tool": "computer_act"})


def test_origin_drops_credentials_path_and_query():
    assert audit.safe_origin("https://user:secret@example.com/path?token=secret") == "https://example.com"
    assert audit.safe_origin("file:///tmp/private") == ""


@pytest.mark.asyncio
async def test_audit_without_bound_session_does_not_touch_database(monkeypatch):
    def fail():
        pytest.fail("audit without context must not connect to DB")

    monkeypatch.setattr(audit, "async_session_factory", fail)
    await audit.record_browser_event(SimpleNamespace(metadata={}), "action_result", action="click_element")
