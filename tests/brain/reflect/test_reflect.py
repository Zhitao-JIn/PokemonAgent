"""`Brain.reflect`：不调模型、不写库、不盖章坐标，只把三段文本原样装进 `Reflection`。

`reflect` 是本版唯一不调模型的公开方法：`before` / `action_text` / `after` 三段按
`Reflection(before=before, action_text=action_text, after=after)` 原样装进结果；
入口 assert 只拦空串（真值判断：`""` 拒、`" "` 收），`prompt` 收下不读，参数关键字
专用，`episode_id` / `step` 由调用方盖章。本文件不用任何 LLM 替身——`Brain()`
不给任何 provider 就能调。
"""

from __future__ import annotations

import pytest

from pokemon_agent.brain import Brain
from pokemon_agent.brain.interface import Reflection


def test_reflect_works_without_any_provider() -> None:
    brain = Brain()

    result = brain.reflect(prompt="p", before="B", after="A", action_text="up")

    assert isinstance(result, Reflection)
    assert result.before == "B"
    assert result.action_text == "up"
    assert result.after == "A"


@pytest.mark.parametrize(
    ("before", "action_text", "after"),
    [
        ("第一行\n第二行", '按 "A" 键', "含中文的结果"),
        ("含 '单引号' 与 \"双引号\"", "a\tb\tc", "结尾有空格  "),
    ],
    ids=["multiline-quotes-chinese", "quotes-tabs-trailing-space"],
)
def test_the_three_fields_pass_through_verbatim(before: str, action_text: str, after: str) -> None:
    brain = Brain()

    result = brain.reflect(prompt="p", before=before, after=after, action_text=action_text)

    assert result.before == before
    assert result.action_text == action_text
    assert result.after == after


def test_pure_whitespace_snapshots_are_accepted_verbatim() -> None:
    brain = Brain()

    result = brain.reflect(prompt="p", before=" ", after="\n", action_text="up")

    assert result.before == " "
    assert result.after == "\n"


def test_action_text_may_be_empty() -> None:
    brain = Brain()

    result = brain.reflect(prompt="p", before="B", after="A", action_text="")

    assert result.action_text == ""


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("", "A", "before"),
        ("B", "", "after"),
        ("", "", "before"),
    ],
    ids=["empty-before", "empty-after", "both-empty"],
)
def test_an_empty_snapshot_trips_the_entry_assert(before: str, after: str, expected: str) -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match=expected):
        brain.reflect(prompt="p", before=before, after=after, action_text="up")


def test_prompt_does_not_affect_the_result() -> None:
    brain = Brain()

    first = brain.reflect(prompt="p1", before="B", after="A", action_text="up")
    second = brain.reflect(prompt="p2", before="B", after="A", action_text="up")

    assert first == second


def test_arguments_are_keyword_only() -> None:
    brain = Brain()

    with pytest.raises(TypeError):
        brain.reflect("p", "B", "A", "up")


def test_calls_are_independent_of_each_other() -> None:
    brain = Brain()

    brain.reflect(prompt="p", before="first-before", after="first-after", action_text="first")

    second = brain.reflect(
        prompt="p", before="second-before", after="second-after", action_text="second"
    )

    assert second.before == "second-before"
    assert second.action_text == "second"
    assert second.after == "second-after"


def test_the_return_type_is_reflection_with_exactly_three_fields() -> None:
    brain = Brain()

    result = brain.reflect(prompt="p", before="B", after="A", action_text="up")

    assert isinstance(result, Reflection)
    assert set(result.model_dump()) == {"before", "action_text", "after"}
