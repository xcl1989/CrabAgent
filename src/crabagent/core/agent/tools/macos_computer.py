"""Provider-neutral macOS computer-use tools backed by the Electron helper.

These mirror the browser computer tools but target allowlisted local macOS app
windows. All safety enforcement (opt-in, allowlist, frontmost check, secure-input
and lock-screen refusal) lives in the Electron main process and the Swift helper;
this module only validates budgets, audits, and relays typed requests.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from crabagent.core.agent.tools.collaboration_browser import _bridge_request, _result
from crabagent.core.agent.tools.registry import registry
from crabagent.core.computer.audit import record_browser_event
from crabagent.core.computer.game_plan import validate_game_plan
from crabagent.core.computer.session import get_session


async def _call_bridge(command: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
    session = get_session(context)
    session.check(observe=command in {"macos_windows", "macos_observe", "macos_capture"})
    with session.track():
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
    await record_browser_event(
        context, "observed", action="macos_windows", decision="executed", url="", observation_id=""
    )
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
    context.metadata["_macos_batch_observation"] = (window_id, pid, time.monotonic())
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
    context.metadata["_macos_batch_observation"] = (window_id, None, time.monotonic())
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
    context.metadata.pop("_macos_batch_observation", None)
    if context.metadata.get("_collab_browser_observation_id") is None and not context.metadata.get(
        "_macos_input_confirmed"
    ):
        # Require a fresh observation before any input, mirroring the browser flow.
        raise RuntimeError("STALE_OBSERVATION: call macos_observe or macos_capture before input")
    return {"windowId": window_id}


async def _input_with_allow_flow(
    command: str, payload: dict[str, Any], context: Any, action: str, started: float
) -> dict[str, Any]:
    """Run one input action with automatic soft-failure recovery.

    - APP_NOT_ALLOWLISTED: ask the user to allow the app once, then retry.
    - WINDOW_NOT_FRONTMOST: the target app lost focus between observation and
      action (common — the host app or a browser steals it back). Auto-activate
      the target app and retry once instead of failing the agent's turn and
      forcing a manual activate → capture → click cycle.
    """
    value = await _call_bridge(command, payload, context)
    error = str(value.get("error", "")) if isinstance(value, dict) else ""

    if "APP_NOT_ALLOWLISTED:" in error:
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
                context,
                "action_result",
                action=action,
                decision="blocked",
                observation_id="",
                url="",
                started=started,
            )
            return {"ok": False, "error": f"用户未允许控制 {bundle_id}", "status": "blocked"}
        await _call_bridge("macos_allow_app", {"bundleId": bundle_id}, context)
        return await _call_bridge(command, payload, context)

    if "WINDOW_NOT_FRONTMOST:" in error and command != "macos_activate":
        bundle_id = (
            error.split("WINDOW_NOT_FRONTMOST:")[-1].strip().split()[0]
            if (error.split("WINDOW_NOT_FRONTMOST:")[-1].strip())
            else ""
        )
        if bundle_id:
            # Activation goes through the same gated flow (consent applies if the
            # bundle was never allowlisted). performActivate also restores/minimizes
            # window creation, so a miniaturized window comes back on screen.
            activated = await _input_with_allow_flow(
                "macos_activate", {"bundleId": bundle_id}, context, "macos_activate", started
            )
            if isinstance(activated, dict) and activated.get("ok"):
                await asyncio.sleep(0.3)  # let focus settle before retrying
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


def _register_input_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    payload_builder,
) -> None:
    """Register a mouse/keyboard input tool sharing the standard macos flow.

    payload_builder(params, context) returns the bridge payload (windowId included
    by the caller's _input_preconditions call inside the builder).
    """

    async def _tool(context=None, **params: Any) -> str:
        session = get_session(context)
        started = time.monotonic()
        payload = payload_builder(params, context)
        try:
            value = await _input_with_allow_flow(name, payload, context, name, started)
        except Exception as exc:
            session.failures += 1
            await record_browser_event(context, "action_result", action=name, decision="failed", started=started)
            raise RuntimeError(str(exc)) from exc
        session.record(value)
        await record_browser_event(context, "action_result", action=name, decision="executed", url="")
        return _result(value)

    _tool.__name__ = name
    registry.register(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required},
        metadata={"source": "builtin", "category": "computer"},
    )(_tool)


_COORD_POINT = {
    "window_id": {"type": "integer"},
    "pid": {"type": "integer"},
    "x": {"type": "integer"},
    "y": {"type": "integer"},
}
_POINT_REQUIRED = ["window_id", "pid", "x", "y"]

_GLOBAL_POINTS_NOTE = (
    " Coordinates are GLOBAL screen points (origin = top-left of the main display). "
    "To convert from a macos_capture image: capture is 1 pixel == 1 window point, so "
    "global = windowFrame.x/y + pixel. The app must be allowlisted and frontmost — "
    "first-time control of a new app asks the user to confirm automatically."
)


def _point_payload_builder():
    def build(params: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = _input_preconditions(context, params["window_id"])
        payload.update(pid=params["pid"], x=params["x"], y=params["y"])
        return payload

    return build


def _drag_payload_builder():
    def build(params: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = _input_preconditions(context, params["window_id"])
        payload.update(
            pid=params["pid"],
            x=params["x"],
            y=params["y"],
            x2=params["x2"],
            y2=params["y2"],
        )
        if params.get("button") and params["button"] != "left":
            payload["button"] = params["button"]
        return payload

    return build


_register_input_tool(
    "macos_double_click",
    "Double-click inside a local macOS app window (open files, select words, zoom) to "
    "carry out actions the user requested." + _GLOBAL_POINTS_NOTE,
    _COORD_POINT,
    _POINT_REQUIRED,
    _point_payload_builder(),
)

_register_input_tool(
    "macos_right_click",
    "Right-click inside a local macOS app window to open context menus on the user's behalf." + _GLOBAL_POINTS_NOTE,
    _COORD_POINT,
    _POINT_REQUIRED,
    _point_payload_builder(),
)

_register_input_tool(
    "macos_move",
    "Move the mouse cursor inside a local macOS app window without clicking, to trigger "
    "hover states, tooltips or menus on the user's behalf." + _GLOBAL_POINTS_NOTE,
    _COORD_POINT,
    _POINT_REQUIRED,
    _point_payload_builder(),
)

_register_input_tool(
    "macos_drag",
    "Drag inside a local macOS app window: press at (x, y), move along an interpolated "
    "path and release at (x2, y2) — for moving windows/items, selecting text, sliders "
    "and canvas drawing." + _GLOBAL_POINTS_NOTE,
    {
        "window_id": {"type": "integer"},
        "pid": {"type": "integer"},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "x2": {"type": "integer"},
        "y2": {"type": "integer"},
        "button": {"type": "string", "enum": ["left", "right", "middle"]},
    },
    ["window_id", "pid", "x", "y", "x2", "y2"],
    _drag_payload_builder(),
)


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
    description="Press a named key or modifier combo in a local macOS app window on the "
    'user\'s behalf, e.g. "return" to send a composed message, "cmd+c"/"cmd+v" for '
    'copy/paste, "shift+down" to extend a text selection. Supported modifiers: cmd, '
    "ctrl, alt, shift. Cmd+Tab and Cmd+Q are refused by design.",
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
    name="macos_hold_game_keys",
    description="Hold 1-4 game keys in a focused local macOS window for 1-1000 ms. "
    "Requires a fresh observation of the same window and PID. Releases are best effort; "
    "process crashes and system failures cannot guarantee key-up.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "pid": {"type": "integer"},
            "keys": {"type": "array", "items": {"type": "string"}},
            "duration_ms": {"type": "integer"},
        },
        "required": ["window_id", "pid", "keys", "duration_ms"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_hold_game_keys(window_id: int, pid: int, keys: list[str], duration_ms: int, context=None) -> str:
    validate_game_plan([{"type": "hold_keys", "keys": keys, "duration_ms": duration_ms}])
    if type(window_id) is not int or window_id <= 0 or type(pid) is not int or pid <= 0:
        raise ValueError("window_id and pid must be positive integers")
    session = get_session(context)
    observation = context.metadata.get("_macos_batch_observation")
    if not observation or observation[:2] != (window_id, pid) or time.monotonic() - observation[2] > 30:
        raise RuntimeError("STALE_OBSERVATION: observe the target window and pid first")
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    action_id = str(uuid.uuid4())
    payload.update(pid=pid, keys=keys, duration_ms=duration_ms, action_id=action_id)
    try:
        # Do not auto-activate or retry: an ambiguous result may already have injected keys.
        value = await _call_bridge("macos_hold_game_keys", payload, context)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(
                asyncio.to_thread(_bridge_request, "macos_cancel_game_keys", {"action_id": action_id}, context=context)
            )
        except Exception:
            pass
        raise
    except Exception:
        session.failures += 1
        await record_browser_event(
            context, "action_result", action="macos_hold_game_keys", decision="failed", started=started
        )
        raise
    if not value.get("ok"):
        session.failures += 1
    else:
        session.record(value)
    await record_browser_event(
        context,
        "action_result",
        action="macos_hold_game_keys",
        decision="executed" if value.get("ok") else "failed",
        started=started,
    )
    return _result(value)


@registry.register(
    name="macos_game_plan",
    description="Execute a bounded sequence of game key holds and waits in one focused macOS "
    "window. Requires a fresh observation of the same window and PID. Key releases are best "
    "effort and cannot be guaranteed after process or system failure. Requires bridge support.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "pid": {"type": "integer"},
            "steps": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["window_id", "pid", "steps"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_game_plan(window_id: int, pid: int, steps: list[dict[str, Any]], context=None) -> str:
    plan = validate_game_plan(steps)
    if type(window_id) is not int or window_id <= 0 or type(pid) is not int or pid <= 0:
        raise ValueError("window_id and pid must be positive integers")
    session = get_session(context)
    observation = context.metadata.get("_macos_batch_observation")
    if not observation or observation[:2] != (window_id, pid) or time.monotonic() - observation[2] > 30:
        raise RuntimeError("STALE_OBSERVATION: observe the target window and pid first")
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    action_id = str(uuid.uuid4())
    normalized = [
        {
            "type": step.kind,
            "duration_ms": step.duration_ms,
            **({"keys": list(step.keys)} if step.kind == "hold_keys" else {}),
        }
        for step in plan.steps
    ]
    payload.update(pid=pid, steps=normalized, action_id=action_id)
    try:
        # Never retry: the helper may have already posted input.
        value = await _call_bridge("macos_game_plan", payload, context)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(
                asyncio.to_thread(_bridge_request, "macos_cancel_game_keys", {"action_id": action_id}, context=context)
            )
        except Exception:
            pass
        raise
    except Exception:
        session.failures += 1
        await record_browser_event(
            context, "action_result", action="macos_game_plan", decision="failed", started=started
        )
        raise
    if value.get("ok"):
        session.record(value)
    else:
        session.failures += 1
    await record_browser_event(
        context,
        "action_result",
        action="macos_game_plan",
        decision="executed" if value.get("ok") else "failed",
        started=started,
    )
    return _result(value)


@registry.register(
    name="macos_scroll",
    description="Scroll inside a local macOS app window on the user's behalf. Positive amounts "
    "scroll down (-2000..2000 pixels). By default the scroll happens at the window center; "
    "pass x/y (GLOBAL screen points, same conversion as macos_click) to scroll at a specific "
    "spot, e.g. inside a nested scrollable area.",
    parameters={
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "amount": {"type": "integer"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["window_id", "amount"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_scroll(window_id: int, amount: int, context=None, x: int | None = None, y: int | None = None) -> str:
    session = get_session(context)
    started = time.monotonic()
    payload = _input_preconditions(context, window_id)
    payload["amount"] = max(-2000, min(2000, amount))
    if x is not None and y is not None:
        payload["x"] = x
        payload["y"] = y
    try:
        value = await _input_with_allow_flow("macos_scroll", payload, context, "macos_scroll", started)
    except Exception as exc:
        session.failures += 1
        await record_browser_event(context, "action_result", action="macos_scroll", decision="failed", started=started)
        raise RuntimeError(str(exc)) from exc
    session.record(value)
    await record_browser_event(context, "action_result", action="macos_scroll", decision="executed", url="")
    return _result(value)


@registry.register(
    name="macos_click_and_type",
    description="Click an observed text field and type text in one operation. Use after "
    "macos_observe or macos_capture of the same window. Coordinates are global screen "
    "points. This does not press Enter or submit; inspect again before further actions. "
    "Existing application permissions and secure input restrictions apply.",
    parameters={
        "type": "object",
        "properties": {**_COORD_POINT, "text": {"type": "string"}},
        "required": ["window_id", "pid", "x", "y", "text"],
    },
    metadata={"source": "builtin", "category": "computer"},
)
async def macos_click_and_type(window_id: int, pid: int, x: int, y: int, text: str, context=None) -> str:
    import json

    if not text or any(char in text for char in "\r\n\t") or len(text.encode("utf-8")) > 10_000:
        raise ValueError("Text must be nonempty, single-line and at most 10000 bytes")
    observation = context.metadata.pop("_macos_batch_observation", None) if context else None
    if (
        not observation
        or observation[0] != window_id
        or observation[1] not in (None, pid)
        or time.monotonic() - observation[2] > 30
    ):
        raise RuntimeError("STALE_OBSERVATION: observe this window again before click and type")
    click = json.loads(await macos_click(window_id, pid, x, y, context=context))
    if click.get("ok") is not True or click.get("status") in {"failed", "blocked"} or click.get("error"):
        return _result({"click": click, "type": {"status": "not_executed"}, "needs_observation": True})
    typed = json.loads(await macos_type(window_id, text, context=context))
    return _result({"click": click, "type": typed, "needs_observation": True})
