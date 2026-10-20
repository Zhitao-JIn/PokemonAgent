"""生产现场与运行结果转为 DeepEval 用例；真值不进入模型请求。"""

import json
from collections.abc import Sequence

from deepeval.test_case import LLMTestCase

from evals.dataset.brain_choose_action import ChooseCase

from .solver import ChooseRun


def build_cases(cases: Sequence[ChooseCase], runs: Sequence[ChooseRun]) -> list[LLMTestCase]:
    """按顺序一一配对，长度不一致抛 ValueError；调用方保证每份请求的目标栈非空。"""
    result: list[LLMTestCase] = []
    for case, run in zip(cases, runs, strict=True):
        assert case.request.goals, "choose case needs a nonempty goal stack"
        actual = (
            {"describe": run.action.describe(), "action": run.action.model_dump(mode="json")}
            if run.action is not None
            else {"failure": run.failure}
        )
        result.append(
            LLMTestCase(
                name=case.case_id,
                input=case.request.goals[-1].goal,
                actual_output=json.dumps(actual, ensure_ascii=False),
                expected_output=json.dumps(
                    [matcher.model_dump(mode="json") for matcher in case.acceptable],
                    ensure_ascii=False,
                ),
                additional_metadata={
                    "scene": str(case.scene),
                    "tags": list(case.tags),
                    "mask": dict(case.request.space.mask),
                },
            )
        )
    return result
