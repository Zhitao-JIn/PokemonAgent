"""自报、世界真值及逐脚本通过率的确定性指标。"""

from typing import Literal

from deepeval.errors import MissingTestCaseParamsError
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .compare import judge_case
from .dataset import ScriptCase
from .solver import ScriptRun


class ScriptSide(BaseMetric):
    """仅比较自报面或真值面；对应问题清单为空为通过。"""

    def __init__(self, side: Literal["code", "truth"], threshold: float = 1.0) -> None:
        self.side = side
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_model = None

    def measure(self, test_case: LLMTestCase) -> float:
        """JSON 必须符合冻结用例与运行记录；格式错误直接上抛。"""
        verdict = judge_case(
            ScriptCase.model_validate_json(test_case.expected_output),
            ScriptRun.model_validate_json(test_case.actual_output),
        )
        problems = getattr(verdict, f"{self.side}_problems")
        self.score = 0.0 if problems else 1.0
        self.reason = "；".join(problems) or "全部符合"
        return self.score

    @property
    def __name__(self) -> str:
        """原生汇总列名。"""
        return self.side


class ScriptPass(BaseMetric):
    """仅计本脚本的用例，自报与世界真值两面都过才通过。"""

    def __init__(self, script: str, threshold: float = 1.0) -> None:
        self.script = script
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_model = None

    def measure(self, test_case: LLMTestCase) -> float:
        """其他脚本用例跳过，不计入本脚本分母。"""
        case = ScriptCase.model_validate_json(test_case.expected_output)
        if case.script != self.script:
            raise MissingTestCaseParamsError("不是本脚本用例")
        verdict = judge_case(case, ScriptRun.model_validate_json(test_case.actual_output))
        self.score = 1.0 if verdict.passed else 0.0
        self.reason = "；".join([*verdict.code_problems, *verdict.truth_problems]) or "全部符合"
        return self.score

    @property
    def __name__(self) -> str:
        """原生逐脚本汇总列名。"""
        return f"pass.{self.script}"
