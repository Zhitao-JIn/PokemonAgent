"""`Brain.summarize`：一次蒸馏的解析（两种外层写法）、失败出口与转发表。

守的是「蒸馏」这条链——摘要对象本身或 `summary` 包裹两种写法都收、`markdown` 保留而
`filename` 丢弃、可选字段有默认、必填字段或评分越界算解析失败并抛
`SummarizeAttemptFailed`、有图走 describe 无图退化 complete、成功恰好一条账。
"""

from __future__ import annotations

import json

import pytest
from _doubles.llm import ScriptedJudge, text_reply, vision_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import SummarizeAttemptFailed, ToolTimeout
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq

PROMPT = "怎么蒸馏"
GOAL = "get the first badge"
HISTORY = ["walked up", "pressed a"]
IMAGE = "data:image/png;base64,AAAA"

LEDGER_KEYS = {
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "ok",
    "raw",
    "prompt",
    "images",
    "started_at",
    "ended_at",
}


def summary_json(**overrides: object) -> str:
    """一份完整合法的摘要 JSON；`overrides` 覆盖或新增键。"""
    data: dict[str, object] = {
        "summary": "took the north road",
        "reason": "reached the gym",
        "reusable_patterns": ["use the north road"],
        "critical_decisions": ["skipped the shop"],
        "failure_points": ["got lost twice"],
        "quality_score": 0.8,
        "quality_rationale": "clear path",
        "applicable_scenes": ["route 2"],
        "tags": ["navigation"],
        "markdown": "# notes",
    }
    data.update(overrides)
    return json.dumps(data)


def test_a_bare_summary_object_parses() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(summary_json())))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    summary = result.summary
    assert summary.summary == "took the north road"
    assert summary.reason == "reached the gym"
    assert summary.reusable_patterns == ["use the north road"]
    assert summary.critical_decisions == ["skipped the shop"]
    assert summary.failure_points == ["got lost twice"]
    assert summary.quality_score == 0.8
    assert summary.quality_rationale == "clear path"
    assert summary.applicable_scenes == ["route 2"]
    assert summary.tags == ["navigation"]
    assert summary.markdown == "# notes"


def test_a_summary_wrapped_in_an_outer_object_parses_too() -> None:
    reply = json.dumps({"summary": json.loads(summary_json())})
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    summary = result.summary
    assert summary.summary == "took the north road"
    assert summary.reason == "reached the gym"
    assert summary.reusable_patterns == ["use the north road"]
    assert summary.critical_decisions == ["skipped the shop"]
    assert summary.failure_points == ["got lost twice"]
    assert summary.quality_score == 0.8
    assert summary.quality_rationale == "clear path"
    assert summary.applicable_scenes == ["route 2"]
    assert summary.tags == ["navigation"]
    assert summary.markdown == "# notes"


def test_the_markdown_field_is_kept_on_the_summary() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(summary_json(markdown="# a\n\nbody"))))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert result.summary.markdown == "# a\n\nbody"


def test_a_filename_in_the_output_is_discarded() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(summary_json(filename="x.md"))))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert "filename" not in result.summary.model_dump()


def test_optional_fields_default_when_the_model_leaves_them_out() -> None:
    reply = json.dumps({"summary": "s", "quality_score": 0.5, "quality_rationale": "r"})
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    summary = result.summary
    assert summary.summary == "s"
    assert summary.reason == ""
    assert summary.reusable_patterns == []
    assert summary.critical_decisions == []
    assert summary.failure_points == []
    assert summary.applicable_scenes == []
    assert summary.tags == []
    assert summary.markdown == ""


def test_a_json_fence_around_the_summary_is_tolerated() -> None:
    reply = "```json\n" + summary_json() + "\n```"
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert result.summary.summary == "took the north road"


@pytest.mark.parametrize("missing_key", ["summary", "quality_score", "quality_rationale"])
def test_missing_required_fields_fail_as_parse_failure(missing_key: str) -> None:
    data = json.loads(summary_json())
    data.pop(missing_key)
    brain = Brain(verify_llm=ScriptedJudge(text_reply(json.dumps(data))))

    with pytest.raises(SummarizeAttemptFailed) as excinfo:
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("score", [1.5, -0.1])
def test_a_quality_score_outside_zero_to_one_fails_as_parse_failure(score: float) -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(summary_json(quality_score=score))))

    with pytest.raises(SummarizeAttemptFailed) as excinfo:
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("reply", ["nope", "[1]"])
def test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text(
    reply: str,
) -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    with pytest.raises(SummarizeAttemptFailed) as excinfo:
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.source == "summarize_episode"
    assert excinfo.value.call.payload["raw"] == reply
    assert excinfo.value.call.payload["input_tokens"] == "11"


def test_summarize_uses_the_verify_provider() -> None:
    verify = ScriptedJudge(text_reply(summary_json()))
    brain = Brain(verify_llm=verify)

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert result.summary
    assert verify.requests == [LlmCompleteReq(prompt=PROMPT)]


def test_summarize_falls_back_to_the_judge_provider_when_no_verify_provider_is_given() -> None:
    judge = ScriptedJudge(text_reply(summary_json()))
    brain = Brain(judge_llm=judge)

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert result.summary
    assert len(judge.requests) == 1


def test_images_go_through_describe_and_no_images_fall_back_to_complete() -> None:
    with_image = ScriptedJudge(vision_reply(summary_json()))
    without_image = ScriptedJudge(text_reply(summary_json()))

    Brain(verify_llm=with_image).summarize(
        prompt=PROMPT,
        goal=GOAL,
        history=HISTORY,
        success=True,
        steps=3,
        max_steps=10,
        images=[IMAGE],
    )
    Brain(verify_llm=without_image).summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    assert with_image.described == [VisionDescribeReq(images=[IMAGE], prompt=PROMPT)]
    assert with_image.requests == []
    assert without_image.requests == [LlmCompleteReq(prompt=PROMPT)]
    assert without_image.described == []


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(summary_json())))

    result = brain.summarize(
        prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
    )

    call = result.calls[0]
    assert len(result.calls) == 1
    assert set(call.payload) == LEDGER_KEYS
    assert call.payload["ok"] == "true"
    assert call.payload["raw"] == summary_json()
    assert call.payload["prompt"] == PROMPT


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    brain = Brain(verify_llm=ScriptedJudge(timeout))

    with pytest.raises(SummarizeAttemptFailed) as excinfo:
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert excinfo.value.__cause__ is timeout
    assert set(excinfo.value.call.payload) == {"ok", "prompt", "images", "started_at", "ended_at"}


def test_summarize_never_retries_by_itself() -> None:
    provider = ScriptedJudge(text_reply("nope"))
    brain = Brain(verify_llm=provider)

    with pytest.raises(SummarizeAttemptFailed):
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )

    assert len(provider.requests) == 1


def test_calling_summarize_without_any_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="verify provider"):
        brain.summarize(
            prompt=PROMPT, goal=GOAL, history=HISTORY, success=True, steps=3, max_steps=10
        )
