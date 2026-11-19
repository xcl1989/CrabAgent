"""Assemble streamed tool calls without guessing between parallel calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(eq=False)
class _Call:
    id: str = ""
    name: str = ""
    index: int | None = None
    fragments: list[tuple[int, str]] = field(default_factory=list)


class ToolCallStream:
    def __init__(self) -> None:
        self._calls: list[_Call] = []
        self._by_index: dict[int, _Call] = {}
        self._by_id: dict[str, _Call] = {}
        self._anonymous: list[tuple[int, str]] = []
        self._sequence = 0
        self._conflict = False

    def add(self, delta) -> None:
        index = getattr(delta, "index", None)
        call_id = getattr(delta, "id", None)
        function = getattr(delta, "function", None)
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        self._sequence += 1
        if not call_id and index is None and not name:
            if arguments:
                self._anonymous.append((self._sequence, arguments))
            return

        by_id = self._by_id.get(call_id) if call_id else None
        by_index = self._by_index.get(index) if index is not None else None
        if by_id is not None and by_index is not None and by_id is not by_index:
            # A declaration can link fragments seen earlier under separate keys.
            if by_index.id or by_id.index is not None or (by_id.name and by_index.name and by_id.name != by_index.name):
                self._conflict = True
                return
            by_id.name = by_id.name or by_index.name
            by_id.fragments.extend(by_index.fragments)
            self._calls.remove(by_index)
            by_index = by_id

        call = by_id or by_index
        if call is None:
            call = _Call()
            self._calls.append(call)
        if ((call_id and call.id and call.id != call_id)
                or (index is not None and call.index is not None and call.index != index)
                or (name and call.name and call.name != name)):
            self._conflict = True
            return
        if call_id:
            self._by_id[call_id] = call
            call.id = call_id
        if index is not None:
            self._by_index[index] = call
            call.index = index
        if name:
            call.name = name
        if arguments:
            call.fragments.append((self._sequence, arguments))

    def finish(self) -> tuple[list[dict], bool]:
        complete = [call for call in self._calls if call.id and call.name]
        ambiguous = self._conflict or len(complete) != len(self._calls)
        if self._anonymous and len(complete) != 1:
            ambiguous = True
        if all(call.index is not None for call in complete):
            complete.sort(key=lambda call: call.index)
        return [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": "" if ambiguous else "".join(
                        text for _, text in sorted(call.fragments + self._anonymous)
                    ),
                },
            }
            for call in complete
        ], ambiguous


class ResponsesToolCallSnapshot:
    """Preserve completed Responses calls before LiteLLM converts them to deltas."""

    def __init__(self) -> None:
        self._completed: list[dict] | None = None

    def attach(self, response) -> None:
        from litellm.completion_extras.litellm_responses_transformation.transformation import (
            OpenAiResponsesToChatCompletionStreamIterator,
        )

        # The ChatGPT normalizer forwards completion_stream to CustomStreamWrapper.
        iterator = getattr(response, "completion_stream", None)
        if not isinstance(iterator, OpenAiResponsesToChatCompletionStreamIterator):
            return
        parse = iterator.chunk_parser

        def capture(event):
            self.observe(event)
            return parse(event)

        iterator.chunk_parser = capture

    def observe(self, event: dict) -> None:
        if not isinstance(event, dict) or event.get("type") != "response.completed":
            return
        response = event.get("response")
        if not isinstance(response, dict):
            return
        output = response.get("output")
        if not isinstance(output, list):
            return
        calls = []
        seen = set()
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            call_id, item_id = item.get("call_id"), item.get("id")
            if not isinstance(call_id, str) or not call_id or re.fullmatch(r"call_\d+", call_id):
                call_id = item_id or call_id
            name, arguments = item.get("name"), item.get("arguments")
            if (not isinstance(call_id, str) or not call_id or call_id in seen
                    or not isinstance(name, str) or not name or not isinstance(arguments, str)):
                return
            seen.add(call_id)
            calls.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}})
        if calls:
            self._completed = calls

    def reconcile(self, calls: list[dict], ambiguous: bool, finish_reason: str | None) -> tuple[list[dict], bool]:
        if self._completed is None or finish_reason != "tool_calls":
            return calls, ambiguous
        completed_names = {call["id"]: call["function"]["name"] for call in self._completed}
        if any(completed_names.get(call["id"]) != call["function"]["name"] for call in calls):
            return calls, True
        # Use the full snapshot, not a patch onto partial arguments: the adapter
        # may assign a continuation to the wrong call as well as drop it.
        return self._completed, False
