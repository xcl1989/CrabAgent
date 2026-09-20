"""The system prompt must carry the proactive task-creation policy so the
agent auto-creates tasks for deliverable work without being asked."""
from __future__ import annotations

import pytest

from crabagent.core.i18n import get_system_prompt_template


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_system_prompt_contains_task_creation_policy(locale):
    prompt = get_system_prompt_template(locale)
    assert prompt, f"missing system prompt template for {locale}"
    assert "task_add" in prompt
    # placehholders must survive so .format(date=..., weekday=..., workspace=...) works
    assert "{date}" in prompt and "{workspace}" in prompt
    # proactive wording: create without being asked
    assert ("无需用户要求" in prompt) or ("do not wait to be asked" in prompt.lower())
    # scope guard: explicit no-task cases are stated
    assert ("不满足以上条件时不建任务" in prompt) or ("Do NOT create a task" in prompt)
