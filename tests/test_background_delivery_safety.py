"""Regression checks for the existing delivery safety boundary.

These tests deliberately do not enable automatic delivery.
"""
from crabagent.core.database import Message
from crabagent.serve.services.message import message_to_dict


def test_task_result_card_is_not_a_safe_background_payload_channel():
    message = Message(role="task_result", content='{"title":"untrusted","status":"done"}')
    converted = message_to_dict(message)
    # Existing cards become user messages; background results must not use them.
    assert converted["role"] == "user"
    assert "untrusted" in converted["content"]


def test_workspace_messages_are_not_a_safe_background_payload_channel():
    message = Message(role="workspace", content="untrusted background output")
    assert message_to_dict(message)["role"] == "user"
