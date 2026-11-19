from types import SimpleNamespace

import pytest

from crabagent.core.agent.tool_call_stream import ToolCallStream


def _delta(index=None, call_id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=args))


def _assemble(*deltas):
    stream = ToolCallStream()
    for delta in deltas:
        stream.add(delta)
    calls, ambiguous = stream.finish()
    return {call["id"]: call["function"]["arguments"] for call in calls}, ambiguous


def test_sparse_out_of_order_calls_with_interleaved_arguments():
    assert _assemble(
        _delta(4, "B", "echo"),
        _delta(2, args='{"a":'),
        _delta(2, "A", "echo"),
        _delta(4, args='{"b":'),
        _delta(2, args='1}'),
        _delta(4, args='2}'),
    ) == ({"A": '{"a":1}', "B": '{"b":2}'}, False)


def test_declaration_links_id_only_and_index_only_fragments_in_arrival_order():
    assert _assemble(
        _delta(3, args='{"a":'),
        _delta(call_id="A", args='1'),
        _delta(3, "A", "echo", '}'),
    ) == ({"A": '{"a":1}'}, False)


def test_single_call_can_receive_unkeyed_fragments():
    assert _assemble(
        _delta(args='{"a":'), _delta(2, "A", "echo"), _delta(args='1}'),
    ) == ({"A": '{"a":1}'}, False)


@pytest.mark.parametrize("extra", [
    _delta(args='{"unkeyed":true}'),
    _delta(2, "different-id", "echo"),
    _delta(5, "A", "echo"),
    _delta(99, args='{"orphan":true}'),
])
def test_ambiguous_batch_never_produces_executable_arguments(extra):
    assert _assemble(
        _delta(2, "A", "echo", '{}'), _delta(4, "B", "echo", '{}'), extra,
    ) == ({"A": "", "B": ""}, True)


def test_responses_adapter_preserves_arguments_across_interleaved_calls():
    from litellm.completion_extras.litellm_responses_transformation.transformation import (
        OpenAiResponsesToChatCompletionStreamIterator,
    )

    wire_events = [
        {"type": "response.function_call_arguments.delta", "output_index": 4, "delta": '{"b":'},
        {"type": "response.output_item.added", "output_index": 2,
         "item": {"type": "function_call", "call_id": "A", "name": "echo", "arguments": ""}},
        {"type": "response.output_item.added", "output_index": 4,
         "item": {"type": "function_call", "call_id": "B", "name": "echo", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '{"a":1}'},
        {"type": "response.function_call_arguments.delta", "output_index": 4, "delta": '2}'},
    ]
    index_map = {}
    stream = ToolCallStream()
    for event in wire_events:
        chunk = OpenAiResponsesToChatCompletionStreamIterator.translate_responses_chunk_to_openai_stream(
            event, index_map
        )
        for delta in chunk.choices[0].delta.tool_calls or ():
            stream.add(delta)
    calls, ambiguous = stream.finish()
    assert not ambiguous
    assert {call["id"]: call["function"]["arguments"] for call in calls} == {"A": '{"a":1}', "B": '{"b":2}'}


def test_completed_responses_snapshot_recovers_parallel_calls_lost_by_adapter():
    from litellm.completion_extras.litellm_responses_transformation.transformation import (
        OpenAiResponsesToChatCompletionStreamIterator,
    )

    from crabagent.core.agent.tool_call_stream import ResponsesToolCallSnapshot

    iterator = OpenAiResponsesToChatCompletionStreamIterator(iter(()), sync_stream=True)
    snapshot = ResponsesToolCallSnapshot()
    from litellm.llms.chatgpt.chat.streaming_utils import ChatGPTToolCallNormalizer

    response = ChatGPTToolCallNormalizer(SimpleNamespace(completion_stream=iterator))
    snapshot.attach(response)
    stream = ToolCallStream()
    items = [
        {"type": "function_call", "call_id": "call_alpha", "name": "echo", "arguments": '{"text":"A"}'},
        {"type": "function_call", "call_id": "call_bravo", "name": "echo", "arguments": '{"text":"B"}'},
    ]
    for idx, item in enumerate(items, start=2):
        chunk = iterator.chunk_parser({"type": "response.output_item.added", "output_index": idx,
                                      "item": dict(item, arguments="")})
        for delta in chunk.choices[0].delta.tool_calls or ():
            stream.add(delta)
        iterator.chunk_parser({"type": "response.output_item.done", "output_index": idx, "item": item})
    terminal = iterator.chunk_parser({"type": "response.completed", "response": {"output": items}})
    calls, ambiguous = stream.finish()
    assert [call["function"]["arguments"] for call in calls] == ["", ""]
    reason = terminal.choices[0].finish_reason
    fixed, ambiguous = snapshot.reconcile(calls, ambiguous, reason)
    assert not ambiguous
    assert [call["function"]["arguments"] for call in fixed] == ['{"text":"A"}', '{"text":"B"}']
    assert snapshot.reconcile(calls, False, "length") == (calls, False)
    calls[0]["function"]["name"] = "different_tool"
    assert snapshot.reconcile(calls, False, reason) == (calls, True)
