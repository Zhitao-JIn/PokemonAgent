"""六个结果袋与 `ModelCall`：`calls`/`extra` 的缺省与互不共享、`JudgeResult` 的缺省与必填。

结果袋都是"硬性字段 + 软性字典（extra）"这个形状，账（calls）也在这里。本文件钉
`calls`/`extra` 的缺省、实例间互不共享、`JudgeResult.interrupted` 缺省 False、
`JudgeResult.why` 必填、`ModelCall` 的成功缺省。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.brain.interface.domain import (
    Action,
    ActionSegment,
    ChooseResult,
    DecomposeResult,
    Decomposition,
    EpisodeSummary,
    JudgeResult,
    ModelCall,
    PlanResult,
    RunPlan,
    SummarizeResult,
    VerifyResult,
    VerifyVerdict,
)

_RESULT_BUILDERS = {
    "ChooseResult": lambda: ChooseResult(action=Action(sequence=[ActionSegment(name="up")])),
    "JudgeResult": lambda: JudgeResult(done=False, why="w"),
    "PlanResult": lambda: PlanResult(plan=RunPlan()),
    "DecomposeResult": lambda: DecomposeResult(
        decomposition=Decomposition(tasks=[{"goal": "a", "success_criteria": "s", "max_steps": 1}])
    ),
    "VerifyResult": lambda: VerifyResult(verdicts=[VerifyVerdict(index=0, positive=True, why="w")]),
    "SummarizeResult": lambda: SummarizeResult(
        summary=EpisodeSummary(summary="s", quality_score=0.5, quality_rationale="q")
    ),
}


@pytest.mark.parametrize("name", list(_RESULT_BUILDERS))
def test_each_result_bag_defaults_calls_and_extra(name: str) -> None:
    result = _RESULT_BUILDERS[name]()

    assert result.calls == []
    assert result.extra == {}


def test_result_bags_do_not_share_calls_or_extra_between_instances() -> None:
    first = JudgeResult(done=False, why="w")
    second = JudgeResult(done=False, why="w")

    first.calls.append(ModelCall())
    first.extra["k"] = "v"

    assert second.calls == []
    assert second.extra == {}


def test_judge_result_defaults_interrupted_to_false() -> None:
    result = JudgeResult(done=False, why="w")

    assert result.interrupted is False


def test_judge_result_requires_a_why() -> None:
    with pytest.raises(ValidationError):
        JudgeResult(done=False)


def test_model_call_defaults_to_success_and_an_empty_payload() -> None:
    call = ModelCall()

    assert call.error_kind == ""
    assert call.error == ""
    assert call.payload == {}
