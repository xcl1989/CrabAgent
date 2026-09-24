from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from crabagent.core.agent.tools.registry import registry
from crabagent.core.computer.audit import record_browser_event
from crabagent.core.computer.session import get_session

_MAX_RESULT_CHARS = 12_000


def _bridge_request(command: str, payload: dict[str, Any] | None = None, *, context: Any = None) -> dict[str, Any]:
    """Send one authenticated command to the local Electron browser bridge."""
    port = os.environ.get("CRAB_COLLAB_BROWSER_PORT", "")
    token = os.environ.get("CRAB_COLLAB_BROWSER_TOKEN", "")
    if not port or not token:
        raise RuntimeError(
            "The collaboration browser is only available in the CrabAgent desktop app. "
            "Open the Collaboration Browser page first."
        )

    action_payload = dict(payload or {})
    mutating_commands = {
        "navigate", "click", "commit_click", "point", "commit_point", "type", "scroll", "select", "press_key",
    }
    if command in mutating_commands:
        action_payload.setdefault("action_id", str(uuid.uuid4()))
    metadata = context.metadata if context is not None else {}
    # The binding is derived from trusted Agent context, never a model argument.
    task_id = str(metadata.get("_run_id") or metadata.setdefault("_computer_task_id", str(uuid.uuid4())))
    body = json.dumps({
        "protocol_version": 1, "runtime_id": "browser:collaboration",
        "task_id": task_id, "trace_id": str(uuid.uuid4()),
        "command": command, "payload": action_payload,
    }).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}/",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    # Navigation and waiting can take a while for slow sites.
    timeout = 120 if command in ("navigate", "wait_for") else 35
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Collaboration browser rejected {command}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach the local collaboration browser: {exc.reason}") from exc

    if "result" not in data:
        raise RuntimeError(str(data.get("detail", "Collaboration browser request failed")))
    return data["result"]


def _result(value: dict[str, Any]) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= _MAX_RESULT_CHARS else text[:_MAX_RESULT_CHARS] + "\n... [truncated]"


def _remember_page_version(context: Any, value: dict[str, Any]) -> dict[str, Any]:
    """Keep the latest Bridge page version for safe follow-up tool calls."""
    if context is not None and isinstance(value.get("page_version"), int):
        context.metadata["_collab_browser_page_version"] = value["page_version"]
        if "observation_id" in value:
            context.metadata["_collab_browser_observation_id"] = value["observation_id"]
    return value


async def _call(command: str, payload: dict[str, Any] | None, context: Any) -> str:
    session = get_session(context)
    observing = command == "observe"
    session.check(observe=observing)
    started = time.monotonic()
    try:
        value = await asyncio.to_thread(lambda: _bridge_request(command, payload, context=context))
    except Exception:
        session.failures += 1
        await record_browser_event(context, "action_result", action=command, decision="failed", started=started)
        raise
    session.record(value, observe=observing)
    if not observing and command not in {"wait_for"} and context is not None:
        context.metadata.pop("_collab_browser_observation_id", None)
    _remember_page_version(context, value)
    await record_browser_event(
        context,
        "observed" if command == "observe" else "action_result",
        action=command,
        decision="executed",
        observation_id=value.get("observation_id", ""),
        url=value.get("url", ""),
        started=started,
    )
    return _result(value)


def _versioned_payload(payload: dict[str, Any], page_version: int | None, context: Any) -> dict[str, Any]:
    version = page_version
    if version is None and context is not None:
        version = context.metadata.get("_collab_browser_page_version")
    if not isinstance(version, int):
        raise RuntimeError("STALE_PAGE: call collab_browser_observe before interacting with the page")
    observation_id = context.metadata.get("_collab_browser_observation_id") if context is not None else None
    if not observation_id:
        raise RuntimeError("STALE_PAGE: call collab_browser_observe before interacting with the page")
    current_version = context.metadata.get("_collab_browser_page_version")
    if version != current_version:
        raise RuntimeError("STALE_PAGE: supplied page version does not match the latest observation")
    return {**payload, "page_version": version, "observation_id": observation_id}


@registry.register(
    name="collab_browser_open",
    description=(
        "Open a URL in the visible shared collaboration browser. The user and AI share "
        "this browser's login state. Only use http or https URLs."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "The website URL to open."}},
        "required": ["url"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_open(url: str, context=None) -> str:
    return await _call("navigate", {"url": url}, context)


@registry.register(
    name="collab_browser_observe",
    description=(
        "Inspect the currently visible shared browser page. Returns page text and numbered "
        "interactive elements. Password values are never exposed. Observe again after navigation."
    ),
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_observe(context=None) -> str:
    return await _call("observe", None, context)


@registry.register(
    name="collab_browser_screenshot",
    description=(
        "Capture a screenshot of the currently visible shared browser page. The image is "
        "returned inline so vision-capable models can inspect visual content."
    ),
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_screenshot(context=None) -> str | list[dict[str, Any]]:
    session = get_session(context)
    session.check(observe=True)
    try:
        value = await asyncio.to_thread(lambda: _bridge_request("computer_observe", context=context))
    except Exception:
        session.failures += 1
        raise
    value = _remember_page_version(context, value)
    data_url = value.pop("data_url", "")
    session.record(value, observe=True)
    if not data_url:
        return _result(value)
    return [
        {"type": "text", "text": _result(value)},
        {"type": "image_url", "image_url": {"url": data_url}, "mime": value.get("mime", "image/png")},
    ]


@registry.register(
    name="collab_browser_click",
    description=(
        "Click a numbered element from the latest collab_browser_observe result using a trusted native mouse event. "
        "Never use this to submit purchases, payments, deletions, account changes, or external messages "
        "without first asking the user for explicit confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "index": {"type": "integer", "description": "Element index from collab_browser_observe."},
            "page_version": {"type": "integer", "description": "Optional observed page version."},
        },
        "required": ["index"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_click(index: int, page_version: int | None = None, context=None) -> str:
    session = get_session(context)
    session.check()
    payload = _versioned_payload({"index": index}, page_version, context)
    started = time.monotonic()
    value = await asyncio.to_thread(lambda: _bridge_request("click", payload, context=context))
    _remember_page_version(context, value)
    if value.get("confirmation_required"):
        await record_browser_event(
            context,
            "approval_requested",
            action="click",
            decision="confirmation_required",
            observation_id=payload["observation_id"],
            url=value.get("url", ""),
            started=started,
        )
    if not value.get("confirmation_required"):
        session.record(value)
        context.metadata.pop("_collab_browser_observation_id", None)
        await record_browser_event(
            context,
            "action_result",
            action="click",
            decision="executed",
            observation_id=payload["observation_id"],
            url=value.get("url", ""),
            started=started,
        )
        return _result(value)
    pending_id = value.get("pending_action_id")
    if context is None or context.confirm_callback is None:
        await record_browser_event(
            context,
            "action_result",
            action="click",
            decision="denied",
            observation_id=payload["observation_id"],
            started=started,
        )
        return _result({"status": "denied", "reason": "An interactive user confirmation is required."})
    try:
        approved = await context.confirm_callback(
            "collab_browser_click",
            {
                "action": "click",
                "label": value.get("label", ""),
                "url": value.get("url", ""),
            },
        )
    except Exception:
        approved = False
    if not approved:
        await record_browser_event(
            context,
            "action_result",
            action="click",
            decision="denied",
            observation_id=payload["observation_id"],
            started=started,
        )
        return _result({"status": "denied", "reason": "The user did not approve the action."})
    commit_payload = {**payload, "pending_action_id": pending_id}
    result = await asyncio.to_thread(lambda: _bridge_request("commit_click", commit_payload, context=context))
    session.record(result)
    context.metadata.pop("_collab_browser_observation_id", None)
    await record_browser_event(
        context,
        "action_result",
        action="click",
        decision="executed",
        observation_id=payload["observation_id"],
        url=result.get("url", ""),
        started=started,
    )
    return _result(_remember_page_version(context, result))


@registry.register(
    name="collab_browser_type",
    description=(
        "Fill a non-sensitive field identified by collab_browser_observe. Never request, read, or enter "
        "passwords, one-time codes, payment data, or identity secrets; ask the user to enter those directly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "index": {"type": "integer", "description": "Element index from collab_browser_observe."},
            "text": {"type": "string", "description": "Non-sensitive text to enter."},
            "page_version": {"type": "integer", "description": "Optional observed page version."},
        },
        "required": ["index", "text"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_type(index: int, text: str, page_version: int | None = None, context=None) -> str:
    return await _call("type", _versioned_payload({"index": index, "text": text}, page_version, context), context)


@registry.register(
    name="collab_browser_scroll",
    description=(
        "Scroll the visible shared collaboration browser page. Positive values scroll down; negative values scroll up."
    ),
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "Pixels to scroll, from -2000 to 2000."},
            "page_version": {"type": "integer", "description": "Optional observed page version."},
        },
        "required": ["amount"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_scroll(amount: int, page_version: int | None = None, context=None) -> str:
    return await _call("scroll", _versioned_payload({"amount": amount}, page_version, context), context)


@registry.register(
    name="collab_browser_select",
    description="Select a non-sensitive option in a select control from the latest observed page.",
    parameters={
        "type": "object",
        "properties": {
            "index": {"type": "integer", "description": "Select element index from collab_browser_observe."},
            "value": {"type": "string", "description": "Option value or visible label."},
            "page_version": {"type": "integer", "description": "Version from collab_browser_observe."},
        },
        "required": ["index", "value"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_select(index: int, value: str, page_version: int | None = None, context=None) -> str:
    return await _call("select", _versioned_payload({"index": index, "value": value}, page_version, context), context)


@registry.register(
    name="collab_browser_press_key",
    description="Press one safe navigation key in the visible collaboration browser.",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "enum": ["Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"],
            },
            "page_version": {"type": "integer", "description": "Version from collab_browser_observe."},
        },
        "required": ["key"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_press_key(key: str, page_version: int | None = None, context=None) -> str:
    return await _call("press_key", _versioned_payload({"key": key}, page_version, context), context)


@registry.register(
    name="collab_browser_wait_for",
    description="Wait until the shared browser finishes loading and optionally shows text or a URL fragment.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Optional visible text that must appear."},
            "url_includes": {"type": "string", "description": "Optional URL fragment that must appear."},
            "timeout_ms": {"type": "integer", "description": "Wait timeout from 100 to 30000 milliseconds."},
        },
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_wait_for(text: str = "", url_includes: str = "", timeout_ms: int = 10000, context=None) -> str:
    return await _call("wait_for", {"text": text, "url_includes": url_includes, "timeout_ms": timeout_ms}, context)


@registry.register(
    name="collab_browser_wait_for_user",
    description=(
        "Pause browser work so the user can complete a login, CAPTCHA, QR scan, MFA, or other human-only step "
        "in the visible shared browser. Resume only after the user responds."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "A concise explanation of the human action needed.",
            }
        },
        "required": ["reason"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def collab_browser_wait_for_user(reason: str, context=None) -> str:
    if context is None or context.ask_callback is None:
        return "Waiting for the user is unavailable in this context. Ask the user to continue manually."
    question = f"请在协作浏览器中完成以下操作，然后回复继续：{reason}"
    answer = await context.ask_callback(question, ["我已完成，继续", "取消此浏览器任务"])
    if "取消" in answer:
        return "The user cancelled the browser task. Stop browser actions and explain the cancellation."
    status = await asyncio.to_thread(lambda: _bridge_request("status", context=context))
    return "The user completed the human-only step. Re-observe the page before continuing.\n" + _result(status)
