"""三条迁移能力的真实重试循环保留版本归因。"""

from pathlib import Path

import pytest
from _doubles.llm import ScriptedJudge, ScriptedLLM, text_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain
from pokemon_agent.direct.brain_tool import Decomposer, Judger, Planner
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.prompt import PromptGateway
from scripts.capture_prompt_golden import GoldenCase, parse_request

GOLDEN = Path(__file__).parent / "golden"


@pytest.mark.parametrize("task", ["run_plan", "decompose", "judge_success"])
@pytest.mark.parametrize("exhausted", [False, True])
def test_planning_and_judging_stamp_all_failed_and_successful_attempts(
    task: str, exhausted: bool
) -> None:
    path = (
        (GOLDEN / "run_plan/synthetic-empty.req.json")
        if task == "run_plan"
        else sorted((GOLDEN / task).glob("history-*.req.json"))[0]
    )
    req = parse_request(GoldenCase.model_validate_json(path.read_bytes()))
    if task == "run_plan":
        req = req.model_copy(update={"details": []})
    elif task == "decompose":
        req = req.model_copy(update={"task_memories": []})
    else:
        req = req.model_copy(update={"history": [], "task_memories": [], "episode_memories": []})
    valid = (
        '{"decision":"continue","why":"继续"}'
        if task == "judge_success"
        else '{"new_items":[],"execution_order":null,"why":"保留"}'
    )
    provider_type = ScriptedJudge if task == "judge_success" else ScriptedLLM
    provider = provider_type(text_reply("invalid"), text_reply("invalid" if exhausted else valid))
    gateway = PromptGateway(None)
    brain = Brain(judge_llm=provider) if task == "judge_success" else Brain(plan_llm=provider)
    capability_type = {"run_plan": Planner, "decompose": Decomposer, "judge_success": Judger}[task]
    capability = capability_type(brain, policy=call_policy(max_attempts=2), prompt_gateway=gateway)
    method = getattr(
        capability, {"run_plan": "plan", "decompose": "decompose", "judge_success": "judge"}[task]
    )

    if exhausted:
        with pytest.raises(MaxRetriesExceeded) as caught:
            method(req)
        calls = caught.value.calls
    else:
        calls = method(req).calls

    assert len(calls) == len(provider.requests) == 2
    for call in calls:
        assert call.payload["prompt_task"] == task
        assert call.payload["prompt_version"] == "v1"
        assert len(call.payload["prompt_hash"]) == 64
    assert calls[0].payload["prompt_hash"] == calls[1].payload["prompt_hash"]
    assert calls[0].error_kind == "ParseFailure"
    assert bool(calls[-1].error_kind) == exhausted
