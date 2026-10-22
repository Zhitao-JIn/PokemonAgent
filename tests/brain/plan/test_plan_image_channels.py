"""规划与拆解按多模态能力分派，账只记录实际发送的图。"""

from collections.abc import Sequence

import pytest
from _doubles.llm import ScriptedJudge, text_reply, vision_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain, Goal
from pokemon_agent.brain.errors import (
    DecomposeAttemptFailed,
    EmptyCompletion,
    PlanAttemptFailed,
    ToolTimeout,
)
from pokemon_agent.brain.interface import DecomposeResult, PlanResult
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq
from pokemon_agent.direct.brain_tool import Planner
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.schemas.memory import EpisodeMemory

FRAMES = ["data:image/png;base64,FIRST", "data:image/png;base64,LAST"]


def _reply(method: str) -> str:
    return (
        '{"why": "retain existing work"}'
        if method == "plan"
        else (
            '{"new_items": [{"goal": "g", "success_criteria": "c", "budge'
            't": {"limit": 1, "unit": "actions"}}], "why": "next step"}'
        )
    )


def _call(
    brain: Brain, method: str, images: Sequence[str], thinking: bool | None = True
) -> PlanResult | DecomposeResult:
    if method == "plan":
        return brain.plan(
            prompt="p", goal_stack=[], history=[], max_push=1, images=images, thinking=thinking
        )
    return brain.decompose(
        prompt="p", goal="g", context=[], max_tasks=1, images=images, thinking=thinking
    )


def test_brain_plan_with_images_uses_describe_and_records_images_in_the_call() -> None:
    provider = ScriptedJudge(vision_reply('{"why": "retain existing work"}'), multimodal=True)

    result = _call(Brain(plan_llm=provider), "plan", FRAMES)

    assert provider.described == [VisionDescribeReq(prompt="p", images=FRAMES)]
    assert provider.requests == []
    assert result.calls[0].payload["images"] == FRAMES
    assert result.calls[0].payload["input_tokens"] == "21"
    assert result.calls[0].payload["thinking_override"] == "true"
    assert "thinking" not in type(provider.described[0]).model_fields


def test_brain_plan_falls_back_to_text_when_the_provider_is_not_multimodal() -> None:
    provider = ScriptedJudge(text_reply('{"why": "retain existing work"}'), multimodal=False)

    result = _call(Brain(plan_llm=provider), "plan", FRAMES, thinking=False)

    assert provider.requests == [LlmCompleteReq(prompt="p", thinking=False)]
    assert provider.described == []
    assert result.calls[0].payload["images"] == []


@pytest.mark.parametrize("multimodal", [True, False])
def test_brain_decompose_with_images_uses_describe_when_available(multimodal: bool) -> None:
    reply = vision_reply(_reply("decompose")) if multimodal else text_reply(_reply("decompose"))
    provider = ScriptedJudge(reply, multimodal=multimodal)

    result = _call(Brain(plan_llm=provider), "decompose", FRAMES)

    assert result.calls[0].payload["images"] == (FRAMES if multimodal else [])
    assert len(provider.described) == int(multimodal)
    assert len(provider.requests) == int(not multimodal)
    if multimodal:
        assert provider.described[0] == VisionDescribeReq(prompt="p", images=FRAMES)
    else:
        assert provider.requests[0] == LlmCompleteReq(prompt="p", thinking=True)


@pytest.mark.parametrize("method", ["plan", "decompose"])
def test_a_multimodal_provider_without_images_still_uses_complete(method: str) -> None:
    provider = ScriptedJudge(text_reply(_reply(method)), multimodal=True)

    result = _call(Brain(plan_llm=provider), method, [])

    assert provider.requests == [LlmCompleteReq(prompt="p", thinking=True)]
    assert provider.described == []
    assert result.calls[0].payload["images"] == []


@pytest.mark.parametrize("method", ["plan", "decompose"])
@pytest.mark.parametrize("failure", ["parse", "provider"])
def test_failed_visual_attempts_record_the_images_that_were_sent(method: str, failure: str) -> None:
    reply = vision_reply("invalid") if failure == "parse" else ToolTimeout("timeout")
    provider = ScriptedJudge(reply, multimodal=True)
    error = PlanAttemptFailed if method == "plan" else DecomposeAttemptFailed

    with pytest.raises(error) as caught:
        _call(Brain(plan_llm=provider), method, FRAMES)

    assert caught.value.call.payload["images"] == FRAMES
    assert provider.described[0].images == FRAMES
    assert caught.value.call.error_kind == ("ParseFailure" if failure == "parse" else "ToolTimeout")


def test_visual_empty_reply_retry_records_false_without_a_thinking_field() -> None:
    provider = ScriptedJudge(
        EmptyCompletion(10, 8, "stop"),
        vision_reply('{"why": "retain existing work"}'),
        multimodal=True,
    )
    memory = EpisodeMemory(
        run_id="r",
        run_goal="总目标",
        episode_id="e",
        goal="g",
        steps=1,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
        first_frame=FRAMES[0],
    )
    request = FromHarnessToBrainToolPlanOnceReq(
        run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
        run_id="r",
        plan=[],
        details=[memory],
        max_push=1,
    )

    result = Planner(
        Brain(plan_llm=provider),
        policy=call_policy(max_attempts=2),
        prompt_gateway=PromptGateway(None),
    ).plan(request)

    assert len(result.calls) == len(provider.described) == 2
    assert provider.requests == []
    assert [call.payload["thinking_override"] for call in result.calls] == ["none", "false"]
    assert all("thinking" not in type(req).model_fields for req in provider.described)
    assert all(req.images == [FRAMES[0]] for req in provider.described)
