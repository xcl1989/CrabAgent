"""Provider-neutral computer tools backed by the visible collaboration browser."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from crabagent.core.agent.tools.collaboration_browser import _bridge_request, _remember_page_version, _result
from crabagent.core.agent.tools.registry import registry
from crabagent.core.computer.audit import record_browser_event
from crabagent.core.computer.session import get_session


async def _call_bridge(command: str, payload=None, *, context=None) -> dict[str, Any]:
    session = get_session(context)
    session.check(observe=command == "computer_observe")
    with session.track():
        return await asyncio.to_thread(_bridge_request, command, payload, context=context)


@registry.register(
    name="computer_observe",
    description="Observe the visible browser with one screenshot, page text, element bounds and an observation ID.",
    parameters={"type": "object", "properties": {}},
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def computer_observe(context=None) -> list[dict[str, Any]]:
    session = get_session(context)
    session.check(observe=True)
    try:
        value = await _call_bridge("computer_observe", context=context)
    except Exception:
        session.failures += 1
        raise
    _remember_page_version(context, value)
    context.metadata["_computer_batch_snapshot"] = {
        key: value.get(key) for key in ("url", "page_version", "viewport", "elements")
    }
    url = value.pop("data_url", "")
    if not url or (url.startswith("data:") and not url.partition(",")[2].strip()):
        session.failures += 1
        raise RuntimeError("CAPTURE_FAILED: collaboration browser returned an empty screenshot")
    mime = value.pop("mime", "image/jpeg")
    session.record(value, observe=True)
    await record_browser_event(
        context, "observed", observation_id=value.get("observation_id", ""), url=value.get("url", "")
    )
    return [
        {"type": "text", "text": _result(value)},
        {"type": "image_url", "image_url": {"url": url}, "mime": mime},
    ]


@registry.register(
    name="computer_act",
    description="Act in the visible shared collaboration browser on the user's behalf: click "
    "elements, type text, select options, scroll, or press keys — up to three sequential "
    "actions tied to a current computer_observe observation. Independent type_text and "
    "select_option fields may execute consecutively after automatic target revalidation; "
    "other actions stop the batch. High-risk actions (visual point "
    "clicks and drags) automatically ask the user for confirmation; do not refuse on the "
    "user's behalf.",
    parameters={
        "type": "object",
        "properties": {
            "observation_id": {"type": "string"},
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "click_element",
                                "click_point",
                                "double_click",
                                "move",
                                "drag",
                                "scroll",
                                "type_text",
                                "keypress",
                                "select_option",
                                "wait",
                            ],
                        },
                        "index": {"type": "integer"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "x2": {"type": "integer"},
                        "y2": {"type": "integer"},
                        "amount": {"type": "integer"},
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "intent": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
        },
        "required": ["observation_id", "actions"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def computer_act(observation_id: str, actions: list[dict[str, Any]], context=None) -> str:
    session = get_session(context)
    if not 1 <= len(actions) <= 3:
        raise ValueError("Batch size must be between 1 and 3")
    if context.metadata.get("_collab_browser_observation_id") != observation_id:
        raise RuntimeError("STALE_OBSERVATION: call computer_observe again")
    results = []
    initial = context.metadata.pop("_computer_batch_snapshot", None)
    used_indices: set[int] = set()
    current_id = observation_id
    for action in actions:
        if results:
            # Only independent, semantically identified fields can be chained.
            if not initial or any(
                item.get("type") not in {"type_text", "select_option"} for item in actions[: len(results) + 1]
            ):
                break
            index = action.get("index")
            if not isinstance(index, int) or isinstance(index, bool) or index in used_indices:
                break
            try:
                session.check(observe=True)
                snapshot = await _call_bridge("observe", context=context)
                session.record(snapshot, observe=True)
                original = next((e for e in initial.get("elements", []) if e.get("index") == index), None)
                fresh = next((e for e in snapshot.get("elements", []) if e.get("index") == index), None)
                if (
                    not original
                    or not fresh
                    or original.get("sensitive")
                    or fresh.get("sensitive")
                    or not original.get("fingerprint")
                    or any(original.get(k) != fresh.get(k) for k in ("fingerprint", "bounds", "tag", "type"))
                    or any(initial.get(k) != snapshot.get(k) for k in ("url", "page_version", "viewport"))
                    or not snapshot.get("observation_id")
                ):
                    break
                _remember_page_version(context, snapshot)
                current_id = snapshot["observation_id"]
            except Exception:
                break
        session.check()
        kind = action.get("type")
        payload: dict[str, Any] = {
            "observation_id": current_id,
            "page_version": context.metadata["_collab_browser_page_version"],
        }
        command = "point"
        if kind == "click_element":
            command = "click"
            payload["index"] = action.get("index")
        elif kind == "type_text":
            command = "type"
            payload.update(index=action.get("index"), text=action.get("text"))
        elif kind == "select_option":
            command = "select"
            payload.update(index=action.get("index"), value=action.get("value"))
        elif kind == "keypress":
            command = "press_key"
            payload["key"] = action.get("key")
        elif kind == "wait":
            command = "wait_for"
            payload["timeout_ms"] = 500
        elif kind in {"click_point", "double_click", "move", "drag", "scroll"}:
            payload.update({k: action[k] for k in ("x", "y", "x2", "y2", "amount") if k in action})
            payload["kind"] = "click" if kind == "click_point" else kind
        else:
            raise ValueError(f"Unsupported computer action: {kind}")
        started = time.monotonic()
        try:
            result = await _call_bridge(command, payload, context=context)
            if result.get("confirmation_required"):
                await record_browser_event(
                    context,
                    "approval_requested",
                    action=kind,
                    decision="confirmation_required",
                    observation_id=observation_id,
                    url=result.get("url", ""),
                    started=started,
                )
                approved = False
                if context.confirm_callback:
                    try:
                        approved = await context.confirm_callback(
                            "computer_act",
                            {
                                "action": kind,
                                "intent": str(action.get("intent", ""))[:100],
                                "target": str(result.get("label", ""))[:100],
                                "url": result.get("url", ""),
                            },
                        )
                    except Exception:
                        approved = False
                if not approved:
                    result = {"status": "blocked", "reason": "Approval denied or unavailable"}
                else:
                    result = await _call_bridge(
                        "commit_click" if command == "click" else "commit_point",
                        {**payload, "pending_action_id": result["pending_action_id"]},
                        context=context,
                    )
            session.record(result)
            await record_browser_event(
                context,
                "action_result",
                action=kind,
                decision=result.get("status", "executed"),
                observation_id=observation_id,
                url=result.get("url", ""),
                started=started,
            )
            results.append({"type": kind, "status": result.get("status", "executed"), "result": result})
            if result.get("status") == "blocked":
                break
        except Exception as exc:
            await record_browser_event(
                context, "action_result", action=kind, decision="failed", observation_id=observation_id, started=started
            )
            session.failures += 1
            results.append({"type": kind, "status": "failed", "error": str(exc)})
            break
        if kind in {"type_text", "select_option"} and isinstance(action.get("index"), int):
            used_indices.add(action["index"])
    for action in actions[len(results) :]:
        results.append({"type": action.get("type"), "status": "not_executed"})
    context.metadata.pop("_collab_browser_observation_id", None)
    return _result({"actions": results, "needs_observation": True})


@registry.register(
    name="computer_hold_game_keys",
    description="Hold up to four game keys simultaneously for at most one second in the "
    "observed collaboration browser. Use only for a game canvas or body with focus. "
    "The keys are released automatically; observe again after the action. Stop remains "
    "available during the hold. This does not support system shortcuts.",
    parameters={
        "type": "object",
        "properties": {
            "observation_id": {"type": "string"},
            "keys": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
            "duration_ms": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "required": ["observation_id", "keys", "duration_ms"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def computer_hold_game_keys(observation_id: str, keys: list[str], duration_ms: int, context=None) -> str:
    from crabagent.core.computer.game_plan import validate_game_plan

    validate_game_plan([{"type": "hold_keys", "keys": keys, "duration_ms": duration_ms}])
    session = get_session(context)
    session.check()
    if context.metadata.get("_collab_browser_observation_id") != observation_id:
        raise RuntimeError("STALE_OBSERVATION: call computer_observe again")
    payload = {
        "observation_id": observation_id,
        "page_version": context.metadata["_collab_browser_page_version"],
        "keys": keys,
        "duration_ms": duration_ms,
    }
    context.metadata.pop("_collab_browser_observation_id", None)
    context.metadata.pop("_computer_batch_snapshot", None)
    started = time.monotonic()
    try:
        result = await _call_bridge("hold_game_keys", payload, context=context)
    except Exception:
        session.failures += 1
        await record_browser_event(
            context, "action_result", action="hold_game_keys", decision="failed", started=started
        )
        raise
    session.record(result)
    await record_browser_event(context, "action_result", action="hold_game_keys", decision="executed", started=started)
    return _result({**result, "needs_observation": True})


@registry.register(
    name="computer_game_plan",
    description="Execute one bounded game input plan against the currently observed focused browser canvas or body. "
    "Each step holds game keys or waits; maximum eight steps and two seconds total. "
    "Keys are released after each hold. Observe again afterwards; do not retry an ambiguous result.",
    parameters={
        "type": "object",
        "properties": {
            "observation_id": {"type": "string"},
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["hold_keys", "wait"]},
                        "keys": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
                        "duration_ms": {"type": "integer", "minimum": 1, "maximum": 1000},
                    },
                    "required": ["type", "duration_ms"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["observation_id", "steps"],
    },
    metadata={"source": "builtin", "category": "collaboration_browser"},
)
async def computer_game_plan(observation_id: str, steps: list[dict[str, Any]], context=None) -> str:
    from crabagent.core.computer.game_plan import validate_game_plan

    validate_game_plan(steps)
    session = get_session(context)
    session.check()
    if context.metadata.get("_collab_browser_observation_id") != observation_id:
        raise RuntimeError("STALE_OBSERVATION: call computer_observe again")
    action_id = str(uuid.uuid4())
    payload = {
        "observation_id": observation_id,
        "page_version": context.metadata["_collab_browser_page_version"],
        "steps": steps,
        "action_id": action_id,
    }
    context.metadata.pop("_collab_browser_observation_id", None)
    context.metadata.pop("_computer_batch_snapshot", None)
    started = time.monotonic()
    try:
        result = await _call_bridge("game_plan", payload, context=context)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(
                asyncio.to_thread(_bridge_request, "cancel_game_plan", {"action_id": action_id}, context=context)
            )
        except Exception:
            pass
        raise
    except Exception:
        session.failures += 1
        await record_browser_event(context, "action_result", action="game_plan", decision="failed", started=started)
        raise
    session.record(result)
    await record_browser_event(context, "action_result", action="game_plan", decision="executed", started=started)
    return _result({**result, "needs_observation": True})
