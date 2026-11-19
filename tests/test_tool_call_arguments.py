import pytest

from crabagent.core.agent.loop import _parse_tool_arguments


@pytest.mark.parametrize(
    ("raw", "finish_reason", "reason"),
    [
        ("", "tool_calls", "no arguments were received"),
        ('{"command":', "tool_calls", "not valid JSON"),
        ('{"command":', "length", "output token limit"),
        ("[]", "tool_calls", "must be a JSON object"),
    ],
)
def test_malformed_tool_arguments_are_not_executed(raw, finish_reason, reason):
    assert reason in _parse_tool_arguments("bash", raw, finish_reason)["_truncated_error"]


def test_valid_tool_arguments_pass_through():
    assert _parse_tool_arguments("bash", '{"command":"pwd"}', "tool_calls") == {"command": "pwd"}
    assert _parse_tool_arguments("status", "{}", "tool_calls") == {}
