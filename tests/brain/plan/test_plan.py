"""`Brain.plan`：run 级规划的一次尝试——解析、失败出口、思考开关与文本回退。

守的是「规划」这条链——模型输出解析成 `RunPlan`、字段不合法算 `ParseFailure` 并抛
`PlanAttemptFailed`（带账、不吞）、未提供 images 时走纯文本（账里 `images` 为 `[]`）、`thinking`
原样进请求并在账里记 `true`/`false`/`none`、成功恰好一条账、自己不重试、没配 provider
就调被入口 assert 拦下、`plan_llm` 缺省回退 `judge_llm`。
"""

from __future__ import annotations

import json

import pytest
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import PlanAttemptFailed, ToolTimeout
from pokemon_agent.brain.schemas import LlmCompleteReq

PROMPT = "怎么规划"
GOAL_STACK = ["beat the first gym"]
HISTORY = ["walked to the gym"]
MAX_PUSH = 2

LEDGER_KEYS = {
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "thinking_override",
    "ok",
    "raw",
    "prompt",
    "images",
    "started_at",
    "ended_at",
}


def plan_json(**overrides: object) -> str:
    """一份完整合法的计划 JSON；`overrides` 覆盖或新增顶层键。"""
    data: dict[str, object] = {
        "new_items": [
            {
                "goal": "reach the gym",
                "success_criteria": "standing in the gym",
                "budget": {"limit": 6, "unit": "tasks"},
            },
            {
                "goal": "beat the leader",
                "success_criteria": "badge obtained",
                "budget": {"limit": 8, "unit": "tasks"},
            },
        ],
        "updates": [{"index": 0, "status": "abandoned", "note": "dead end"}],
        "why": "gym first",
    }
    data.update(overrides)
    return json.dumps(data)


def test_a_valid_plan_object_parses_into_a_run_plan() -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(plan_json())))

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    plan = result.plan
    assert [g.goal for g in plan.push_goals] == ["reach the gym", "beat the leader"]
    assert plan.push_goals[0].max_steps == 6
    assert len(plan.updates) == 1
    assert plan.updates[0].index == 0
    assert plan.updates[0].status == "abandoned"
    assert plan.updates[0].note == "dead end"
    assert plan.why == "gym first"


def test_a_json_fence_around_the_plan_is_tolerated() -> None:
    reply = "```json\n" + plan_json() + "\n```"
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert result.plan.why == "gym first"


def test_an_empty_object_requires_a_reason() -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply("{}")))

    with pytest.raises(PlanAttemptFailed):
        brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)


def test_an_update_index_beyond_the_table_is_passed_through_for_the_caller_to_drop() -> None:
    reply = plan_json(updates=[{"index": 9, "status": "pending", "note": "retry"}])
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert result.plan.updates[0].index == 9
    assert result.plan.updates[0].note == "retry"


@pytest.mark.parametrize(
    ("reply", "keyword"),
    [
        (
            plan_json(
                new_items=[
                    {"goal": "", "success_criteria": "s", "budget": {"limit": 6, "unit": "tasks"}}
                ]
            ),
            "goal",
        ),
        (
            plan_json(
                new_items=[
                    {"goal": "g", "success_criteria": "s", "budget": {"limit": 0, "unit": "tasks"}}
                ]
            ),
            "limit",
        ),
        (plan_json(updates=[{"index": -1, "status": "pending"}]), "index"),
        (plan_json(updates=[{"index": 0, "status": "completed"}]), "status"),
        (plan_json(push_goals="x"), "push_goals"),
    ],
)
def test_an_invalid_plan_field_fails_as_parse_failure_naming_the_field(
    reply: str, keyword: str
) -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    with pytest.raises(PlanAttemptFailed) as excinfo:
        brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.source == "plan"
    assert "RunPlan" in excinfo.value.call.error
    assert keyword in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("reply", ["nope", "[1]"])
def test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text(
    reply: str,
) -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    with pytest.raises(PlanAttemptFailed) as excinfo:
        brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.call.payload["raw"] == reply
    assert excinfo.value.call.payload["input_tokens"] == "11"
    assert excinfo.value.call.payload["output_tokens"] == "7"


@pytest.mark.parametrize(("reply", "raises"), [(plan_json(), False), ("nope", True)])
def test_plan_without_images_uses_text_and_records_an_empty_image_list(
    reply: str, raises: bool
) -> None:
    provider = ScriptedLLM(text_reply(reply))
    brain = Brain(plan_llm=provider)

    if raises:
        with pytest.raises(PlanAttemptFailed) as excinfo:
            brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)
        payload = excinfo.value.call.payload
    else:
        payload = (
            brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)
            .calls[0]
            .payload
        )

    assert payload["images"] == []
    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]


@pytest.mark.parametrize(
    ("thinking", "override_str"),
    [(True, "true"), (False, "false"), (None, "none")],
)
def test_the_thinking_override_reaches_the_request_and_the_ledger(
    thinking: bool | None, override_str: str
) -> None:
    provider = ScriptedLLM(text_reply(plan_json()))
    brain = Brain(plan_llm=provider)

    result = brain.plan(
        prompt=PROMPT,
        goal_stack=GOAL_STACK,
        history=HISTORY,
        max_push=MAX_PUSH,
        thinking=thinking,
    )

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT, thinking=thinking)]
    assert result.calls[0].payload["thinking_override"] == override_str


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(plan_json())))

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    call = result.calls[0]
    assert len(result.calls) == 1
    assert set(call.payload) == LEDGER_KEYS
    assert call.payload["ok"] == "true"
    assert call.payload["input_tokens"] == "11"
    assert call.payload["output_tokens"] == "7"
    assert call.payload["cached_tokens"] == "3"
    assert call.payload["reasoning_tokens"] == "2"
    assert call.payload["raw"] == plan_json()
    assert call.payload["prompt"] == PROMPT
    assert call.payload["images"] == []
    assert call.payload["thinking_override"] == "none"
    assert isinstance(call.payload["started_at"], float)
    assert isinstance(call.payload["ended_at"], float)
    assert call.payload["started_at"] <= call.payload["ended_at"]
    assert call.error_kind == ""
    assert call.error == ""


def test_the_prompt_reaches_the_provider_verbatim_whatever_the_materials_say() -> None:
    provider = ScriptedLLM(text_reply(plan_json()))
    brain = Brain(plan_llm=provider)

    brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]


def test_plan_falls_back_to_the_judge_provider_when_no_plan_provider_is_given() -> None:
    judge = ScriptedLLM(text_reply(plan_json()))
    brain = Brain(judge_llm=judge)

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert result.plan.why == "gym first"
    assert len(judge.requests) == 1


def test_an_explicit_plan_provider_is_used_instead_of_the_judge_provider() -> None:
    judge = ScriptedLLM()
    plan = ScriptedLLM(text_reply(plan_json()))
    brain = Brain(judge_llm=judge, plan_llm=plan)

    result = brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert result.plan.why == "gym first"
    assert len(plan.requests) == 1
    assert judge.requests == []


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    brain = Brain(plan_llm=ScriptedLLM(timeout))

    with pytest.raises(PlanAttemptFailed) as excinfo:
        brain.plan(
            prompt=PROMPT,
            goal_stack=GOAL_STACK,
            history=HISTORY,
            max_push=MAX_PUSH,
            thinking=True,
        )

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert "gateway down" in excinfo.value.call.error
    assert excinfo.value.__cause__ is timeout
    assert set(excinfo.value.call.payload) == {
        "provider",
        "model",
        "ok",
        "prompt",
        "images",
        "thinking_override",
        "started_at",
        "ended_at",
    }
    assert excinfo.value.call.payload["thinking_override"] == "true"


def test_plan_never_retries_by_itself() -> None:
    provider = ScriptedLLM(text_reply("nope"))
    brain = Brain(plan_llm=provider)

    with pytest.raises(PlanAttemptFailed):
        brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)

    assert len(provider.requests) == 1


def test_calling_plan_without_any_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="plan provider"):
        brain.plan(prompt=PROMPT, goal_stack=GOAL_STACK, history=HISTORY, max_push=MAX_PUSH)
