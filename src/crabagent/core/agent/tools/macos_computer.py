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
    description="Bring a local macOS app to the front or launch it by bundle ID, so its windows "
    "can be inspected and operated on the user's behalf. First-time control of a new app asks "
    "the user for consent automatically. Use macos_windows afterwards to find the window.",
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
    "Start here to operate a local app on the user's behalf: pick a window, then macos_observe "
    "it before acting.",
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
    description="Inspect a local macOS app window's accessibility tree (roles, labels, values, "
    "frames) to plan clicks or typing on the user's behalf. Returns structured elements; macOS "
    "accessibility permission must be granted on this machine.",
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
    description="Screenshot one local macOS app window (JPEG) to check UI state before or after "
    "acting on the user's behalf. Requires Screen Recording permission.",
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
    if isinstance(value, dict) and "windowFrame" in value:
        frame = value["windowFrame"] or {}
        ox, oy = frame.get("x", 0), frame.get("y", 0)
        text += (
            "\n\n[坐标换算] 截图 1 像素 == 窗口 1 逻辑点。macos_click 需要全局屏幕坐标："
            f"global_x = {ox} + 像素x，global_y = {oy} + 像素y。"
        )
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
    description="Click inside a local macOS app window (buttons, links, list rows) to carry out "
    "actions the user requested, e.g. operating a chat app to send a message. Coordinates are "
    "GLOBAL screen points (origin = top-left of the main display). To convert from a "
    "macos_capture image: capture is 1 pixel == 1 window point, so global = windowFrame.x/y + "
    "pixel. The app must be allowlisted and frontmost — first-time control of a new app asks "
    "the user to confirm automatically.",
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
    description="Type Unicode text into a local macOS app window on the user's behalf, e.g. "
    "composing a message in a chat app (max 10000 bytes). Observe the window first with "
    "macos_observe or macos_capture.",
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
    description="Press a named key (return/escape/tab/space/delete/up/down/left/right) in a "
    "local macOS app window on the user's behalf, e.g. pressing return to send a composed "
    "message.",
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
    description="Scroll inside a local macOS app window on the user's behalf. Positive scrolls "
    "down (-2000..2000 pixels).",
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
