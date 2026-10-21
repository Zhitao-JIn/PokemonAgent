"""真实失败请求的结构纠错：不替模型补任务，重试明确告知合法待办引用。"""

import json

from _doubles.llm import ScriptedLLM, text_reply

from evals.brain_decompose.dataset import load
from evals.brain_plan.dataset import load as load_plans
from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import ToolTimeout
from pokemon_agent.direct.brain_tool import Decomposer, Planner


def test_retry_explains_missing_and_nonexistent_references_and_keeps_both_calls():
    case = next(
        row
        for row in load("v20261020_1846")
        if row.case_id == "knowledge_door_transition.episode.decompose.000008"
    )
    invalid = {
        "new_items": [],
        "updates": [{"index": 0, "status": "abandoned", "note": "放弃失败路线"}],
        "execution_order": ["new:0", "new:1", "existing:2"],
        "why": "保留其余待办",
    }
    corrected = {**invalid, "execution_order": ["existing:1", "existing:2"]}
    model = ScriptedLLM(text_reply(json.dumps(invalid)), text_reply(json.dumps(corrected)))

    response = Decomposer(Brain(plan_llm=model), max_attempts=2).decompose(case.request)

    assert response.decomposition.execution_order == ["existing:1", "existing:2"]
    assert len(response.calls) == 2
    assert response.calls[0].error_kind == "ParseFailure"
    error = response.calls[0].error
    assert "合法引用=['existing:1', 'existing:2']" in error
    assert "缺少=['existing:1']" in error
    assert "非法=['new:0', 'new:1']" in error
    assert error in response.calls[1].payload["prompt"]
    assert not response.calls[1].error_kind


def test_plan_parse_retry_includes_the_same_correction_channel():
    case = load_plans("v20261020_1846")[0]
    invalid = {"new_items": [], "execution_order": ["new:0"], "why": "保留"}
    valid = {"new_items": [], "execution_order": None, "why": "保留"}
    model = ScriptedLLM(text_reply(json.dumps(invalid)), text_reply(json.dumps(valid)))

    response = Planner(Brain(plan_llm=model), max_attempts=2).plan(case.request)

    assert len(response.calls) == 2
    assert response.calls[0].error in response.calls[1].payload["prompt"]


def test_decompose_transport_retry_does_not_invent_a_parse_correction():
    case = load("v20261020_1846")[0]
    valid = {"new_items": [], "execution_order": None, "why": "保留"}
    model = ScriptedLLM(ToolTimeout("network timeout"), text_reply(json.dumps(valid)))

    response = Decomposer(Brain(plan_llm=model), max_attempts=2).decompose(case.request)

    assert len(response.calls) == 2
    assert response.calls[0].error_kind == "ToolTimeout"
    assert response.calls[1].payload["prompt"] == response.calls[0].payload["prompt"]
