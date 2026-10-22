"""`Brain.judge`：一次判定尝试的解析、失败出口与转发表。

守的是「独立判定」这条链——模型怎么写怎么读、解析不出就抛 `JudgeAttemptFailed`（带账、
不吞、不静默降级）、有图走 `describe()` 无图退化 `complete()`（provider 类型自带
describe，不查 multimodal——这点与 choose 不同）、成功恰好一条账、自己不重试、没配
provider 就调被入口 assert 拦下。
"""

from __future__ import annotations

import pytest
from _doubles.llm import ScriptedJudge, text_reply, vision_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import JudgeAttemptFailed, ToolTimeout
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq

PROMPT = "怎么判"
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


def test_done_true_is_a_success_verdict() -> None:
    brain = Brain(
        judge_llm=ScriptedJudge(text_reply('{"why": "badge on screen", "decision": "achieved"}'))
    )

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert result.done is True
    assert result.interrupted is False
    assert result.why == "badge on screen"


def test_done_false_is_a_not_yet_verdict() -> None:
    brain = Brain(
        judge_llm=ScriptedJudge(text_reply('{"why": "still in town", "decision": "continue"}'))
    )

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert result.done is False
    assert result.interrupted is False
    assert result.why == "still in town"


@pytest.mark.parametrize(
    ("reply", "expected_done", "expected_interrupted"),
    [
        ('{"decision": "interrupted", "why": "observed evidence"}', False, True),
        ('{"decision": "achieved", "why": "observed evidence"}', True, False),
        ('{"decision": "continue", "why": "observed evidence"}', False, False),
        ('{"decision": "continue", "why": "observed evidence"}', False, False),
    ],
)
def test_interrupted_is_only_honoured_when_done_is_false(
    reply: str, expected_done: bool, expected_interrupted: bool
) -> None:
    brain = Brain(judge_llm=ScriptedJudge(text_reply(reply)))

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert result.done is expected_done
    assert result.interrupted is expected_interrupted


@pytest.mark.parametrize(
    "reply",
    [
        '{"decision": "achieved"}',
        '{"why": "", "decision": "achieved"}',
        '{"why": null, "decision": "achieved"}',
    ],
)
def test_a_missing_or_empty_why_is_a_parse_failure(reply: str) -> None:
    brain = Brain(judge_llm=ScriptedJudge(text_reply(reply)))

    with pytest.raises(JudgeAttemptFailed):
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)


def test_a_json_fence_around_the_verdict_is_tolerated() -> None:
    brain = Brain(
        judge_llm=ScriptedJudge(text_reply('```json\n{"why": "no", "decision": "continue"}\n```'))
    )

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert result.done is False
    assert result.why == "no"


@pytest.mark.parametrize(
    "reply",
    ['{"done": "yes"}', '{"done": 1}', '{"why": "x"}', '[{"done": true}]'],
)
def test_a_missing_or_non_boolean_done_fails_as_parse_failure(reply: str) -> None:
    brain = Brain(judge_llm=ScriptedJudge(text_reply(reply)))

    with pytest.raises(JudgeAttemptFailed) as excinfo:
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


def test_non_json_output_fails_as_parse_failure_and_keeps_the_raw_text() -> None:
    brain = Brain(judge_llm=ScriptedJudge(text_reply("nope")))

    with pytest.raises(JudgeAttemptFailed) as excinfo:
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.source == "judge"
    assert excinfo.value.call.payload["raw"] == "nope"
    assert excinfo.value.call.payload["ok"] == "false"
    assert excinfo.value.call.payload["input_tokens"] == "11"
    assert excinfo.value.call.payload["output_tokens"] == "7"


def test_images_go_through_describe() -> None:
    provider = ScriptedJudge(vision_reply('{"decision": "achieved", "why": "observed evidence"}'))
    brain = Brain(judge_llm=provider)

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY, images=[IMAGE, IMAGE])

    assert provider.described == [VisionDescribeReq(images=[IMAGE, IMAGE], prompt=PROMPT)]
    assert provider.requests == []
    assert result.calls[0].payload["images"] == [IMAGE, IMAGE]


def test_no_images_fall_back_to_plain_completion() -> None:
    provider = ScriptedJudge(text_reply('{"decision": "achieved", "why": "observed evidence"}'))
    brain = Brain(judge_llm=provider)

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]
    assert provider.described == []
    assert result.calls[0].payload["images"] == []


def test_the_two_response_shapes_land_in_the_same_ledger_keys() -> None:
    vision = Brain(
        judge_llm=ScriptedJudge(
            vision_reply('{"decision": "achieved", "why": "observed evidence"}')
        )
    )
    text = Brain(
        judge_llm=ScriptedJudge(text_reply('{"decision": "achieved", "why": "observed evidence"}'))
    )

    vision_payload = (
        vision.judge(prompt=PROMPT, goal=GOAL, history=HISTORY, images=[IMAGE]).calls[0].payload
    )
    text_payload = text.judge(prompt=PROMPT, goal=GOAL, history=HISTORY).calls[0].payload

    assert set(vision_payload) == LEDGER_KEYS
    assert set(text_payload) == LEDGER_KEYS
    assert vision_payload["input_tokens"] == "21"
    assert vision_payload["output_tokens"] == "9"
    assert vision_payload["cached_tokens"] == "4"
    assert vision_payload["reasoning_tokens"] == "5"
    assert text_payload["input_tokens"] == "11"
    assert text_payload["output_tokens"] == "7"
    assert text_payload["cached_tokens"] == "3"
    assert text_payload["reasoning_tokens"] == "2"


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    brain = Brain(judge_llm=ScriptedJudge(text_reply('{"why": "ok", "decision": "achieved"}')))

    result = brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    call = result.calls[0]
    assert len(result.calls) == 1
    assert set(call.payload) == LEDGER_KEYS
    assert call.payload["ok"] == "true"
    assert call.payload["raw"] == '{"why": "ok", "decision": "achieved"}'
    assert call.payload["prompt"] == PROMPT
    assert isinstance(call.payload["started_at"], float)
    assert isinstance(call.payload["ended_at"], float)
    assert call.payload["started_at"] <= call.payload["ended_at"]
    assert call.error_kind == ""
    assert call.error == ""


def test_the_prompt_reaches_the_provider_verbatim_whatever_goal_and_history_say() -> None:
    provider = ScriptedJudge(text_reply('{"decision": "achieved", "why": "observed evidence"}'))
    brain = Brain(judge_llm=provider)

    brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    brain = Brain(judge_llm=ScriptedJudge(timeout))

    with pytest.raises(JudgeAttemptFailed) as excinfo:
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert "gateway down" in excinfo.value.call.error
    assert excinfo.value.__cause__ is timeout
    assert set(excinfo.value.call.payload) == {"ok", "prompt", "images", "started_at", "ended_at"}
    assert excinfo.value.call.payload["ok"] == "false"


def test_judge_never_retries_by_itself() -> None:
    provider = ScriptedJudge(text_reply("nope"))
    brain = Brain(judge_llm=provider)

    with pytest.raises(JudgeAttemptFailed):
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)

    assert len(provider.requests) == 1


def test_calling_judge_without_a_judge_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="judge provider"):
        brain.judge(prompt=PROMPT, goal=GOAL, history=HISTORY)
