import pytest

from crabagent.core.computer.game_plan import validate_game_plan


def test_valid_plan_is_immutable_and_normalized():
    plan = validate_game_plan(
        [
            {"type": "hold_keys", "keys": ["ArrowRight", "KeyW"], "duration_ms": 300},
            {"type": "wait", "duration_ms": 80},
        ]
    )
    assert plan.total_ms == 380
    assert plan.steps[0].keys == ("ArrowRight", "KeyW")


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"type": "hold_keys", "keys": ["KeyW", "KeyW"], "duration_ms": 1}],
        [{"type": "hold_keys", "keys": ["Command", "KeyQ"], "duration_ms": 1}],
        [{"type": "hold_keys", "keys": ["KeyW"], "duration_ms": True}],
        [{"type": "hold_keys", "keys": ["KeyW"], "duration_ms": 1001}],
        [{"type": "wait", "duration_ms": 1000}] * 3,
        [{"type": "wait", "duration_ms": 1}] * 9,
        [{"type": "click", "x": 1, "y": 1, "duration_ms": 1}],
        [{"type": "wait", "duration_ms": 1, "keys": ["KeyW"]}],
        [{"type": "hold_keys", "keys": [["KeyW"]], "duration_ms": 1}],
    ],
)
def test_rejects_invalid_plan(steps):
    with pytest.raises(ValueError):
        validate_game_plan(steps)
