"""Provider-neutral computer tools backed by the visible collaboration browser."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from crabagent.core.agent.tools.collaboration_browser import _bridge_request, _remember_page_version, _result
from crabagent.core.agent.tools.registry import registry
from crabagent.core.computer.audit import record_browser_event
from crabagent.core.computer.session import get_session


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
        value = await asyncio.to_thread(_bridge_request, "computer_observe", context=context)
    except Exception:
        session.failures += 1
        raise
    _remember_page_version(context, value)
    url = value.pop("data_url")
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
    "actions tied to a current computer_observe observation. High-risk actions (visual point "
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
    for action in actions:
        session.check()
        kind = action.get("type")
        payload: dict[str, Any] = {
            "observation_id": observation_id,
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
            result = await asyncio.to_thread(_bridge_request, command, payload, context=context)
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
                    result = await asyncio.to_thread(
                        _bridge_request,
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
        # Never reuse a pre-action observation, including after pointer movement or scroll.
        break
    for action in actions[len(results) :]:
        results.append({"type": action.get("type"), "status": "not_executed"})
    context.metadata.pop("_collab_browser_observation_id", None)
    return _result({"actions": results, "needs_observation": True})
