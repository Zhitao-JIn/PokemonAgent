"""`Brain.verify`：逐条正/负样本标记的解析、失败出口与转发表。

守的是「校验」这条链——`verdicts` 与 `entries` 等长且按 `index` 顺序、漏条补负样本、
裸数组 / `verdicts` 包裹 / 围栏三种写法都收、解析不出就抛 `VerifyAttemptFailed`（不
静默降级成「全部标负」）、有图走 describe 无图退化 complete、成功恰好一条账。
"""

from __future__ import annotations

import json

import pytest
from _doubles.llm import ScriptedJudge, text_reply, vision_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import ToolTimeout, VerifyAttemptFailed
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq

PROMPT = "怎么校验"
GOAL = "get the first badge"
KNOWLEDGE = "gym doors open after the trainer is beaten"
ENTRIES = ["entered the gym", "talked to the guide", "left the gym"]
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

VERDICTS = [
    {"index": 0, "positive": True, "why": "a"},
    {"index": 1, "positive": False, "why": "b"},
    {"index": 2, "positive": True, "why": "c"},
]


def test_verdicts_come_back_the_same_length_as_the_entries_and_in_index_order() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(json.dumps({"verdicts": VERDICTS}))))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert len(result.verdicts) == len(ENTRIES)
    assert [v.index for v in result.verdicts] == [0, 1, 2]
    assert [v.positive for v in result.verdicts] == [True, False, True]
    assert [v.why for v in result.verdicts] == ["a", "b", "c"]


def test_a_missing_index_is_marked_negative_not_a_parse_failure() -> None:
    reply = json.dumps(
        [{"index": 0, "positive": True, "why": "a"}, {"index": 2, "positive": True, "why": "c"}]
    )
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert result.verdicts[1].positive is False
    assert result.verdicts[1].why
    assert result.verdicts[0].positive is True
    assert result.verdicts[0].why == "a"
    assert result.verdicts[2].positive is True
    assert result.verdicts[2].why == "c"


def test_out_of_order_answers_are_returned_in_index_order() -> None:
    reply = json.dumps(
        [
            {"index": 2, "positive": True, "why": "c"},
            {"index": 0, "positive": True, "why": "a"},
            {"index": 1, "positive": False, "why": "b"},
        ]
    )
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert [v.index for v in result.verdicts] == [0, 1, 2]
    assert [v.why for v in result.verdicts] == ["a", "b", "c"]


def test_duplicate_indexes_still_yield_one_verdict_per_entry() -> None:
    reply = json.dumps(
        [
            {"index": 0, "positive": True, "why": "first"},
            {"index": 0, "positive": False, "why": "second"},
            {"index": 1, "positive": False, "why": "b"},
            {"index": 2, "positive": True, "why": "c"},
        ]
    )
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert len(result.verdicts) == 3
    assert [v.index for v in result.verdicts] == [0, 1, 2]


def test_indexes_outside_the_entries_are_dropped() -> None:
    reply = json.dumps(
        [
            {"index": 0, "positive": True, "why": "a"},
            {"index": 1, "positive": False, "why": "b"},
            {"index": 2, "positive": True, "why": "c"},
            {"index": 9, "positive": True, "why": "z"},
            {"index": -1, "positive": True, "why": "neg"},
        ]
    )
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert len(result.verdicts) == 3
    assert [v.index for v in result.verdicts] == [0, 1, 2]


def test_a_verdict_without_a_positive_field_counts_as_negative() -> None:
    reply = json.dumps([{"index": 0, "why": "x"}])
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert result.verdicts[0].positive is False
    assert result.verdicts[0].why == "x"


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps(VERDICTS),
        json.dumps({"verdicts": VERDICTS}),
        "```json\n" + json.dumps(VERDICTS) + "\n```",
    ],
)
def test_the_answer_may_be_a_bare_array_or_wrapped_in_verdicts_or_fenced(reply: str) -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert [v.index for v in result.verdicts] == [0, 1, 2]
    assert [v.positive for v in result.verdicts] == [True, False, True]
    assert [v.why for v in result.verdicts] == ["a", "b", "c"]


@pytest.mark.parametrize("reply", ["nope", '{"foo": 1}', '[{"index": "abc"}]'])
def test_unparseable_output_raises_instead_of_marking_everything_unreliable(reply: str) -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(reply)))

    with pytest.raises(VerifyAttemptFailed) as excinfo:
        brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.source == "verify"
    assert excinfo.value.call.payload["ok"] == "false"
    assert excinfo.value.call.payload["raw"] == reply


def test_verify_does_no_filtering_of_its_own() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(json.dumps(VERDICTS))))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert len(result.verdicts) == 3
    assert [v.positive for v in result.verdicts] == [True, False, True]


def test_no_entries_yield_no_verdicts() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply("[]")))

    result = brain.verify(prompt=PROMPT, entries=[], goal=GOAL, knowledge=KNOWLEDGE)

    assert result.verdicts == []
    assert len(result.calls) == 1


def test_verify_falls_back_to_the_judge_provider_when_no_verify_provider_is_given() -> None:
    judge = ScriptedJudge(text_reply(json.dumps(VERDICTS)))
    brain = Brain(judge_llm=judge)

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert result.verdicts
    assert len(judge.requests) == 1


def test_an_explicit_verify_provider_is_used_instead_of_the_judge_provider() -> None:
    judge = ScriptedJudge()
    verify = ScriptedJudge(text_reply(json.dumps(VERDICTS)))
    brain = Brain(judge_llm=judge, verify_llm=verify)

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert result.verdicts
    assert len(verify.requests) == 1
    assert judge.requests == []


def test_images_go_through_describe_and_no_images_fall_back_to_complete() -> None:
    with_image = ScriptedJudge(vision_reply(json.dumps(VERDICTS)))
    without_image = ScriptedJudge(text_reply(json.dumps(VERDICTS)))

    Brain(verify_llm=with_image).verify(
        prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE, images=[IMAGE]
    )
    Brain(verify_llm=without_image).verify(
        prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE
    )

    assert with_image.described == [VisionDescribeReq(images=[IMAGE], prompt=PROMPT)]
    assert with_image.requests == []
    assert without_image.requests == [LlmCompleteReq(prompt=PROMPT)]
    assert without_image.described == []


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    brain = Brain(verify_llm=ScriptedJudge(text_reply(json.dumps(VERDICTS))))

    result = brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    call = result.calls[0]
    assert len(result.calls) == 1
    assert set(call.payload) == LEDGER_KEYS
    assert call.payload["ok"] == "true"
    assert call.payload["input_tokens"] == "11"
    assert call.payload["output_tokens"] == "7"
    assert call.payload["cached_tokens"] == "3"
    assert call.payload["reasoning_tokens"] == "2"
    assert call.payload["prompt"] == PROMPT
    assert call.payload["images"] == []


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    brain = Brain(verify_llm=ScriptedJudge(timeout))

    with pytest.raises(VerifyAttemptFailed) as excinfo:
        brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert excinfo.value.__cause__ is timeout
    assert set(excinfo.value.call.payload) == {"ok", "prompt", "images", "started_at", "ended_at"}


def test_verify_never_retries_by_itself() -> None:
    provider = ScriptedJudge(text_reply("nope"))
    brain = Brain(verify_llm=provider)

    with pytest.raises(VerifyAttemptFailed):
        brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)

    assert len(provider.requests) == 1


def test_calling_verify_without_any_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="verify provider"):
        brain.verify(prompt=PROMPT, entries=ENTRIES, goal=GOAL, knowledge=KNOWLEDGE)
