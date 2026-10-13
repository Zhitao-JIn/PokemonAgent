"""六列视觉指标；评分不调模型，未标注字段原生跳过。"""

import json

from deepeval.errors import MissingTestCaseParamsError
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .compare import field_verdict


class FieldMatch(BaseMetric):
    """单个视觉字段与独立标注比较。"""

    def __init__(self, key: str, threshold: float = 1.0) -> None:
        self.key = key
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_model = None

    def measure(self, test_case: LLMTestCase) -> float:
        """期望缺键时跳过，格式错误直接上抛。"""
        verdict = field_verdict(
            json.loads(test_case.actual_output), json.loads(test_case.expected_output), self.key
        )
        if verdict.value == "N":
            raise MissingTestCaseParamsError(verdict.reason)
        self.score = 1.0 if verdict.value == "C" else 0.0
        self.reason = verdict.reason
        return self.score

    @property
    def __name__(self) -> str:
        """原生汇总列名。"""
        return self.key
