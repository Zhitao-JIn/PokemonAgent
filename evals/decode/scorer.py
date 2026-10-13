"""确定性字段指标；未标注通过 DeepEval 原生机制跳过。"""

import json
from collections.abc import Sequence

from deepeval.errors import MissingTestCaseParamsError
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from evals.dataset.frames.schemas import ScreenSample

from .compare import GROUPS, Group, field_verdict, truth_for


class FieldMatch(BaseMetric):
    """单字段精确匹配；无 LLM，缺真值不进指标分母。"""

    def __init__(self, name: str, group: str, key: str, threshold: float = 1.0) -> None:
        self.name = name
        self.group = group
        self.key = key
        self.threshold = threshold
        self.evaluation_model = None
        self.async_mode = False
        self.strict_mode = False

    def measure(
        self, test_case: LLMTestCase, *, _show_indicator: bool = True, _in_component: bool = False
    ) -> float:
        """要求两份输出为 JSON；缺标抛跳过异常，JSON 错误上抛。"""
        actual = json.loads(test_case.actual_output)
        expected = json.loads(test_case.expected_output)
        verdict = field_verdict(actual.get(self.group, {}), expected.get(self.group), self.key)
        if verdict.value == "N":
            raise MissingTestCaseParamsError(f"{self.name}: {verdict.reason}")
        self.score = 1.0 if verdict.value == "C" else 0.0
        self.reason = verdict.reason
        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self) -> bool:
        """返回本次已计分字段是否通过。"""
        return self.error is None and self.score is not None and self.score >= self.threshold

    @property
    def __name__(self) -> str:
        """DeepEval 原生汇总的指标名。"""
        return self.name


def build_metrics(frames: Sequence[ScreenSample]) -> list[FieldMatch]:
    """扫描真值键并集；不硬编码字段或计分数量。"""
    fields: set[tuple[Group, str]] = {
        (group, key)
        for frame in frames
        for group in GROUPS
        for key in (truth_for(frame, group) or {})
    }
    return [FieldMatch(f"{group}.{key}", group, key) for group, key in sorted(fields)]
