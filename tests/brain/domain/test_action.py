"""`Action` / `ActionSegment`：动作的形状约束、`describe()` 与 `segments()` 的行为。

`Action` 从大脑吐出交给世界执行，两种形状恰好取一：按键链（`sequence`）或脚本调用
（`script`）；`describe()` 把动作渲染成 trace/记忆里的文本，`segments()` 返回规范化
按键链的副本。本文件只钉项目自己声明的约束与默认值，不测 pydantic 框架本身。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.brain.interface.domain import Action, ActionSegment, ScriptCall


def test_a_key_chain_action_has_no_script() -> None:
    action = Action(sequence=[ActionSegment(name="up")])

    assert action.script is None


def test_a_script_action_has_an_empty_sequence() -> None:
    action = Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2}))

    assert action.sequence == []


def test_an_action_with_neither_a_sequence_nor_a_script_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Action()


def test_an_action_with_both_a_sequence_and_a_script_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Action(
            sequence=[ActionSegment(name="up")],
            script=ScriptCall(name="wait"),
        )


def test_describe_names_a_single_key_without_the_times_suffix() -> None:
    action = Action(sequence=[ActionSegment(name="up")])

    assert action.describe() == "up"


def test_describe_joins_segments_with_an_arrow_and_marks_multi_presses() -> None:
    action = Action(sequence=[ActionSegment(name="up"), ActionSegment(name="a", times=3)])

    assert action.describe() == "up -> a×3"


def test_describe_renders_a_script_with_its_arguments() -> None:
    action = Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2}))

    assert action.describe() == "script:walk_to(x=5, y=2)"


def test_describe_renders_a_script_without_arguments_as_empty_parens() -> None:
    action = Action(script=ScriptCall(name="wait"))

    assert action.describe() == "script:wait()"


def test_a_script_action_has_no_segments() -> None:
    action = Action(script=ScriptCall(name="wait"))

    assert action.segments() == []


def test_segments_returns_a_copy_that_does_not_touch_the_action() -> None:
    action = Action(sequence=[ActionSegment(name="up")])

    action.segments().append(ActionSegment(name="down"))

    assert len(action.sequence) == 1


def test_an_action_segment_requires_a_non_empty_name() -> None:
    with pytest.raises(ValidationError):
        ActionSegment(name="")


def test_an_action_segment_defaults_to_a_single_press() -> None:
    segment = ActionSegment(name="up")

    assert segment.times == 1


@pytest.mark.parametrize("times", [0, -1])
def test_an_action_segment_rejects_a_non_positive_times(times: int) -> None:
    with pytest.raises(ValidationError):
        ActionSegment(name="up", times=times)
