"""brain 的异常词汇：继承树、默认 source、字段、与 AgentError 的分工、导出一致性。

`pokemon_agent/brain/errors.py` 里 15 个异常是 brain 自持的失败词汇：根 `BrainError`
（不是项目顶层的 `AgentError`——brain 要能被整体拷走，不欠外部基类）；`AttemptFailed`
家族六子类对应六个方法、各自带默认 `source`；其余八类各有自己的字段。replay 靠类名
统计失败类型，外部 `except BrainError` / `except AttemptFailed` 依赖这套继承关系。
本文件只测这些关系，不测 provider 产出异常（那在 providers/ 目录）。
"""

from __future__ import annotations

import pytest

import pokemon_agent.brain.errors as errors_module
from pokemon_agent.brain.errors import (
    AttemptFailed,
    BrainError,
    DecisionAttemptFailed,
    DecomposeAttemptFailed,
    EmptyCompletion,
    IllegalAction,
    ImageNotDelivered,
    JudgeAttemptFailed,
    OutputTruncated,
    ParseFailure,
    PlanAttemptFailed,
    ProviderRejected,
    SummarizeAttemptFailed,
    ToolTimeout,
    VerifyAttemptFailed,
)
from pokemon_agent.brain.interface import ModelCall
from pokemon_agent.errors import AgentError

ALL_ERROR_NAMES = [
    "BrainError",
    "ParseFailure",
    "IllegalAction",
    "EmptyCompletion",
    "OutputTruncated",
    "ToolTimeout",
    "ProviderRejected",
    "ImageNotDelivered",
    "AttemptFailed",
    "DecisionAttemptFailed",
    "PlanAttemptFailed",
    "DecomposeAttemptFailed",
    "JudgeAttemptFailed",
    "VerifyAttemptFailed",
    "SummarizeAttemptFailed",
]

ATTEMPT_FAILED_DEFAULT_SOURCES = [
    (DecisionAttemptFailed, "choose"),
    (PlanAttemptFailed, "plan"),
    (DecomposeAttemptFailed, "decompose"),
    (JudgeAttemptFailed, "judge"),
    (VerifyAttemptFailed, "verify"),
    (SummarizeAttemptFailed, "summarize_episode"),
]


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_every_brain_error_inherits_from_brain_error(name: str) -> None:
    cls = getattr(errors_module, name)

    assert issubclass(cls, BrainError)


@pytest.mark.parametrize("name", ALL_ERROR_NAMES)
def test_no_brain_error_descends_from_the_project_agent_error(name: str) -> None:
    cls = getattr(errors_module, name)

    assert not issubclass(cls, AgentError)


@pytest.mark.parametrize(
    ("name", "is_attempt_failed"),
    [
        ("DecisionAttemptFailed", True),
        ("PlanAttemptFailed", True),
        ("DecomposeAttemptFailed", True),
        ("JudgeAttemptFailed", True),
        ("VerifyAttemptFailed", True),
        ("SummarizeAttemptFailed", True),
        ("ParseFailure", False),
        ("IllegalAction", False),
        ("EmptyCompletion", False),
        ("OutputTruncated", False),
        ("ToolTimeout", False),
        ("ProviderRejected", False),
        ("ImageNotDelivered", False),
    ],
)
def test_attempt_failed_subclassing_matches_the_chain_layout(
    name: str, is_attempt_failed: bool
) -> None:
    cls = getattr(errors_module, name)

    assert issubclass(cls, AttemptFailed) is is_attempt_failed


@pytest.mark.parametrize(
    ("cls", "expected_source"),
    ATTEMPT_FAILED_DEFAULT_SOURCES,
    ids=[cls.__name__ for cls, _ in ATTEMPT_FAILED_DEFAULT_SOURCES],
)
def test_each_attempt_failed_subclass_defaults_its_source_and_keeps_the_call(
    cls: type[AttemptFailed], expected_source: str
) -> None:
    call = ModelCall(error_kind="ParseFailure", error="bad json")

    exc = cls(call)

    assert exc.source == expected_source
    assert exc.call is call


def test_an_explicit_source_overrides_the_default_and_shows_up_in_the_message() -> None:
    call = ModelCall(error_kind="X", error="Y")

    exc = DecisionAttemptFailed(call, "custom")

    assert exc.source == "custom"
    assert "custom" in str(exc)


def test_the_attempt_failed_base_defaults_to_an_empty_source_and_uses_the_class_name() -> None:
    call = ModelCall(error_kind="X", error="Y")

    exc = AttemptFailed(call)

    assert exc.source == ""
    assert str(exc).startswith("[AttemptFailed]")


def test_attempt_failed_message_carries_the_error_kind_and_error() -> None:
    call = ModelCall(error_kind="IllegalAction", error="chose fly")

    exc = DecisionAttemptFailed(call)

    assert "IllegalAction" in str(exc)
    assert "chose fly" in str(exc)


def test_parse_failure_remembers_the_raw_text_and_reason() -> None:
    exc = ParseFailure('{"a"', "not valid json")

    assert exc.raw_text == '{"a"'
    assert exc.reason == "not valid json"
    assert '{"a"' in str(exc)
    assert "not valid json" in str(exc)


def test_illegal_action_remembers_the_name_and_the_allowed_set() -> None:
    exc = IllegalAction("fly", ["up", "down"])

    assert exc.name == "fly"
    assert exc.allowed == ["up", "down"]
    assert "fly" in str(exc)
    assert "['up', 'down']" in str(exc)


def test_empty_completion_remembers_its_three_fields_in_the_message() -> None:
    exc = EmptyCompletion(10, 8, "stop")

    assert exc.completion_tokens == 10
    assert exc.reasoning_tokens == 8
    assert exc.finish_reason == "stop"
    assert "completion_tokens=10" in str(exc)
    assert "reasoning_tokens=8" in str(exc)
    assert "finish_reason='stop'" in str(exc)


def test_output_truncated_remembers_the_token_count() -> None:
    exc = OutputTruncated(512)

    assert exc.tokens == 512
    assert "512 tokens" in str(exc)


def test_image_not_delivered_remembers_the_input_tokens_and_floor() -> None:
    exc = ImageNotDelivered(30, 200)

    assert exc.input_tokens == 30
    assert exc.floor == 200
    assert "input_tokens=30 < floor=200" in str(exc)


def test_tool_timeout_and_provider_rejected_are_distinct_and_catchable() -> None:
    assert not issubclass(ToolTimeout, ProviderRejected)
    assert not issubclass(ProviderRejected, ToolTimeout)

    with pytest.raises(BrainError):
        raise ToolTimeout("gateway down")
    with pytest.raises(BrainError):
        raise ProviderRejected("401")


def test_the_all_list_names_exactly_the_brain_error_subclasses() -> None:
    subclasses = {
        name
        for name, obj in vars(errors_module).items()
        if isinstance(obj, type) and issubclass(obj, BrainError)
    }

    assert subclasses == set(errors_module.__all__)
