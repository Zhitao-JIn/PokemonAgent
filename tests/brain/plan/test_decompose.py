"""`Brain.decompose`：episode 级拆解的一次尝试——解析、失败出口、思考开关与文本回退。

守的是「拆解」这条链——模型输出解析成 `Decomposition`、字段不合法算 `ParseFailure` 并抛
`DecomposeAttemptFailed`（带账、不吞）、未提供 images 时走纯文本、`thinking` 进请求与账、成功恰好
一条账、自己不重试、没配 provider 或 `max_tasks` 非正数被入口 assert 拦下、`plan_llm`
缺省回退 `judge_llm`。
"""

from __future__ import annotations

import json

import pytest
from _doubles.llm import ScriptedLLM, text_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import DecomposeAttemptFailed, ToolTimeout
from pokemon_agent.brain.schemas import LlmCompleteReq

PROMPT = "怎么拆解"
GOAL = "get the first badge"
CONTEXT = ["badge case is empty"]
MAX_TASKS = 3

LEDGER_KEYS = {
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


def chain_json(**overrides: object) -> str:
    """一份完整合法的任务链 JSON；`overrides` 覆盖或新增顶层键。"""
    data: dict[str, object] = {
        "tasks": [
            {"goal": "reach the gym", "success_criteria": "standing in the gym", "max_steps": 6},
            {"goal": "beat the leader", "success_criteria": "badge obtained", "max_steps": 8},
        ],
        "why": "gym first",
    }
    data.update(overrides)
    return json.dumps(data)


def test_a_valid_decomposition_parses_into_an_ordered_task_chain() -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(chain_json())))

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    chain = result.decomposition
    assert [t.goal for t in chain.tasks] == ["reach the gym", "beat the leader"]
    assert [t.max_steps for t in chain.tasks] == [6, 8]
    assert chain.why == "gym first"


def test_a_json_fence_around_the_chain_is_tolerated() -> None:
    reply = "```json\n" + chain_json() + "\n```"
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert len(result.decomposition.tasks) == 2


def test_the_explanation_is_optional() -> None:
    data = json.loads(chain_json())
    data.pop("why")
    brain = Brain(plan_llm=ScriptedLLM(text_reply(json.dumps(data))))

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert result.decomposition.why == ""


@pytest.mark.parametrize(
    ("reply", "keyword"),
    [
        ("{}", "tasks"),
        (json.dumps({"tasks": [], "why": "x"}), "tasks"),
        (chain_json(tasks=[{"goal": "g", "success_criteria": "s", "max_steps": 0}]), "max_steps"),
        (chain_json(tasks=[{"goal": "", "success_criteria": "s", "max_steps": 6}]), "goal"),
    ],
)
def test_an_invalid_chain_fails_as_parse_failure_naming_the_field(reply: str, keyword: str) -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    with pytest.raises(DecomposeAttemptFailed) as excinfo:
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.source == "decompose"
    assert "Decomposition" in excinfo.value.call.error
    assert keyword in excinfo.value.call.error
    assert excinfo.value.call.payload["ok"] == "false"


@pytest.mark.parametrize("reply", ["nope", "[1]"])
def test_non_json_or_non_object_output_fails_as_parse_failure_and_keeps_the_raw_text(
    reply: str,
) -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(reply)))

    with pytest.raises(DecomposeAttemptFailed) as excinfo:
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert excinfo.value.call.error_kind == "ParseFailure"
    assert excinfo.value.call.payload["raw"] == reply
    assert excinfo.value.call.payload["input_tokens"] == "11"


@pytest.mark.parametrize("max_tasks", [0, -1])
def test_a_non_positive_max_tasks_trips_the_entry_assert_before_any_model_call(
    max_tasks: int,
) -> None:
    provider = ScriptedLLM(text_reply(chain_json()))
    brain = Brain(plan_llm=provider)

    with pytest.raises(AssertionError, match="max_tasks"):
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=max_tasks)

    assert provider.requests == []


def test_decompose_uses_the_plan_provider() -> None:
    judge = ScriptedLLM()
    plan = ScriptedLLM(text_reply(chain_json()))
    brain = Brain(judge_llm=judge, plan_llm=plan)

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert len(result.decomposition.tasks) == 2
    assert len(plan.requests) == 1
    assert judge.requests == []


def test_decompose_falls_back_to_the_judge_provider_when_no_plan_provider_is_given() -> None:
    judge = ScriptedLLM(text_reply(chain_json()))
    brain = Brain(judge_llm=judge)

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert len(result.decomposition.tasks) == 2
    assert len(judge.requests) == 1


@pytest.mark.parametrize(
    ("thinking", "override_str"),
    [(True, "true"), (False, "false"), (None, "none")],
)
def test_the_thinking_override_reaches_the_request_and_the_ledger(
    thinking: bool | None, override_str: str
) -> None:
    provider = ScriptedLLM(text_reply(chain_json()))
    brain = Brain(plan_llm=provider)

    result = brain.decompose(
        prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS, thinking=thinking
    )

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT, thinking=thinking)]
    assert result.calls[0].payload["thinking_override"] == override_str


def test_a_successful_attempt_returns_exactly_one_ledger_entry() -> None:
    brain = Brain(plan_llm=ScriptedLLM(text_reply(chain_json())))

    result = brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    call = result.calls[0]
    assert len(result.calls) == 1
    assert set(call.payload) == LEDGER_KEYS
    assert call.payload["ok"] == "true"
    assert call.payload["images"] == []
    assert call.payload["prompt"] == PROMPT
    assert call.payload["raw"] == chain_json()


def test_the_prompt_reaches_the_provider_verbatim_whatever_the_materials_say() -> None:
    provider = ScriptedLLM(text_reply(chain_json()))
    brain = Brain(plan_llm=provider)

    brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]


def test_a_provider_exception_becomes_an_attempt_failure_with_a_ledger_entry() -> None:
    timeout = ToolTimeout("gateway down")
    brain = Brain(plan_llm=ScriptedLLM(timeout))

    with pytest.raises(DecomposeAttemptFailed) as excinfo:
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert excinfo.value.call.error_kind == "ToolTimeout"
    assert excinfo.value.__cause__ is timeout
    assert set(excinfo.value.call.payload) == {
        "ok",
        "prompt",
        "images",
        "thinking_override",
        "started_at",
        "ended_at",
    }


def test_decompose_never_retries_by_itself() -> None:
    provider = ScriptedLLM(text_reply("nope"))
    brain = Brain(plan_llm=provider)

    with pytest.raises(DecomposeAttemptFailed):
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)

    assert len(provider.requests) == 1


def test_calling_decompose_without_any_provider_trips_the_entry_assert() -> None:
    brain = Brain()

    with pytest.raises(AssertionError, match="plan provider"):
        brain.decompose(prompt=PROMPT, goal=GOAL, context=CONTEXT, max_tasks=MAX_TASKS)
