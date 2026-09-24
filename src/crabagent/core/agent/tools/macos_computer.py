"""Provider-neutral macOS computer-use tools backed by the Electron helper.

These mirror the browser computer tools but target allowlisted local macOS app
windows. All safety enforcement (opt-in, allowlist, frontmost check, secure-input
and lock-screen refusal) lives in the Electron main process and the Swift helper;
this module only validates budgets, audits, and relays typed requests.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from crabagent.core.agent.tools.collaboration_browser import _bridge_request, _result
from crabagent.core.agent.tools.registry import registry
from crabagent.core.computer.audit import record_browser_event
from crabagent.core.computer.session import get_session


async def _call_bridge(command: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
    return await asyncio.to_thread(_bridge_request, command, payload, context=context)


@registry.register(
    name="macos_activate",
    description="Activate (bring to front) or launch a macOS app by bundle ID. Launching and "
    "activation both require the app to be in the allowlist; the user is asked to confirm "
    "new apps. Use macos_windows afterwards to find the window.",
    parameters={
        "type": "object",
        "properties": {"bundle_id": {"type": "string"}},
        "required": ["bundle_id"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_activate(bundle_id: str, context=None) -> str:
    session = get_session(context)
    session.check()
    started = time.monotonic()
    try:
        value = await _input_with_allow_flow(
            "macos_activate", {"bundleId": bundle_id}, context, "macos_activate", started
        )
    except Exception as exc:
        session.failures += 1
        await record_browser_event(
            context, "action_result", action="macos_activate", decision="failed", started=started
        )
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_activate", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_windows",
    description="List on-screen macOS app windows (windowId, pid, bundleId, title, bounds). "
    "Use a windowId with macos_observe before acting.",
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_windows(context=None) -> str:
    session = get_session(context)
    session.check(observe=True)
    value = await _call_bridge("macos_windows", {}, context)
    session.record(value, observe=True)
    await record_browser_event(context, "observed", action="macos_windows", decision="executed",
                               url="", observation_id="")
    return _result(value)


@registry.register(
    name="macos_observe",
    description="Observe an allowlisted macOS app window: accessibility tree with roles, labels, "
    "values and frames. Requires macOS input to be enabled and permissions granted.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "pid": {"type": "integer"},
        },
        "required": ["window_id", "pid"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_observe(window_id: int, pid: int, context=None) -> str:
    session = get_session(context)
    session.check(observe=True)
    started = time.monotonic()
    try:
        value = await _call_bridge("macos_observe", {"windowId": window_id, "pid": pid}, context)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_observe", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value, observe=True)
    # Mark the input precondition: a fresh macOS observation happened in this context.
    context.metadata["_macos_input_confirmed"] = True
    await record_browser_event(context, "observed", action="macos_observe", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_capture",
    description="Capture a screenshot of one macOS app window (JPEG). Requires Screen Recording "
    "permission.",
    parameters={
        "type": "object",
        "properties": {"window_id": {"type": "integer"}},
        "required": ["window_id"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_capture(window_id: int, context=None) -> list[dict[str, Any]]:
    session = get_session(context)
    session.check(observe=True)
    started = time.monotonic()
    try:
        value = await _call_bridge("macos_capture", {"windowId": window_id}, context)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_capture", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value, observe=True)
    context.metadata["_macos_input_confirmed"] = True
    await record_browser_event(context, "observed", action="macos_capture", decision="executed", url="")
    data_url = value.pop("dataUrl", "")
    text = _result(value)
    if not data_url:
        return [{"type": "text", "text": text}]
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": data_url}, "mime": "image/jpeg"},
    ]


def _input_preconditions(context: Any, window_id: int) -> dict[str, Any]:
    session = get_session(context)
    session.check()
    if context.metadata.get("_collab_browser_observation_id") is None and not context.metadata.get(
        "_macos_input_confirmed"
    ):
        # Require a fresh observation before any input, mirroring the browser flow.
        raise RuntimeError("STALE_OBSERVATION: call macos_observe or macos_capture before input")
    return {"windowId": window_id}


async def _input_with_allow_flow(
    command: str, payload: dict[str, Any], context: Any, action: str, started: float
) -> dict[str, Any]:
    """Run one input action; on APP_NOT_ALLOWLISTED ask the user to allow the app once."""
    value = await _call_bridge(command, payload, context)
    error = str(value.get("error", "")) if isinstance(value, dict) else ""
    if "APP_NOT_ALLOWLISTED:" not in error:
        return value
    bundle_id = error.split("APP_NOT_ALLOWLISTED:")[-1].strip().split()[0]
    approved = False
    if getattr(context, "confirm_callback", None):
        try:
            approved = await context.confirm_callback(
                "macos_allow_app",
                {"bundleId": bundle_id, "intent": "AI 请求获得对该应用窗口的键鼠控制权限"},
            )
        except Exception:
            approved = False
    if not approved:
        await record_browser_event(
            context, "action_result", action=action, decision="blocked",
            observation_id="", url="", started=started,
        )
        return {"ok": False, "error": f"用户未允许控制 {bundle_id}", "status": "blocked"}
    await _call_bridge("macos_allow_app", {"bundleId": bundle_id}, context)
    value = await _call_bridge(command, payload, context)
    return value


@registry.register(
    name="macos_click",
    description="Click at coordinates inside a macOS app window (global screen coordinates from "
    "the window frame). The target app must be allowlisted and frontmost.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "pid": {"type": "integer"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["window_id", "pid", "x", "y"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_click(window_id: int, pid: int, x: int, y: int, context=None) -> str:
    session = get_session(context)
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    payload.update(pid=pid, x=x, y=y)
    try:
        value = await _input_with_allow_flow("macos_click", payload, context, "macos_click", started)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_click", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_click", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_type",
    description="Type Unicode text into the focused macOS app window (max 10000 bytes).",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "text": {"type": "string"},
        },
        "required": ["window_id", "text"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_type(window_id: int, text: str, context=None) -> str:
    session = get_session(context)
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    payload["text"] = text[:10_000]
    try:
        value = await _input_with_allow_flow("macos_type", payload, context, "macos_type", started)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_type", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_type", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_key",
    description="Press a named key (return/escape/tab/space/delete/up/down/left/right) in the "
    "focused macOS app window.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "key": {"type": "string"},
        },
        "required": ["window_id", "key"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_key(window_id: int, key: str, context=None) -> str:
    session = get_session(context)
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    payload["key"] = key
    try:
        value = await _input_with_allow_flow("macos_key", payload, context, "macos_key", started)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_key", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_key", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_scroll",
    description="Scroll inside a macOS app window. Positive scrolls down (-2000..2000 pixels).",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "amount": {"type": "integer"},
        },
        "required": ["window_id", "amount"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_scroll(window_id: int, amount: int, context=None) -> str:
    session = get_session(context)
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    payload["amount"] = max(-2000, min(2000, amount))
    try:
        value = await _input_with_allow_flow("macos_scroll", payload, context, "macos_scroll", started)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_scroll", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_scroll", decision="executed", url="")
    return _result(value)
