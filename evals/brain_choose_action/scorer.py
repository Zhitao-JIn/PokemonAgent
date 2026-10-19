"""确定性指标：可接受、已解析、掩码合法，以及按现场场合与难点分组。"""

from collections.abc import Sequence

from deepeval.errors import MissingTestCaseParamsError
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from pydantic import TypeAdapter

from evals.dataset.brain_choose_action import ActionMatcher, ChooseCase
from pokemon_agent.world import ActionSpace

from .compare import is_legal, matches
from .solver import ChooseRun


class _Metric(BaseMetric):
    """确定性同步指标的共同契约，不装配任何评分模型。"""

    def __init__(self, threshold: float = 1.0) -> None:
        """保存同名构造参数；缺标由 MissingTestCaseParamsError 交框架跳过。"""
        self.threshold = threshold
        self.evaluation_model = None
        self.async_mode = False
        self.strict_mode = False

    def _record(self, passed: bool, reason: str) -> float:
        """记录本次分值、理由与通过状态。"""
        self.score = float(passed)
        self.reason = reason
        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self) -> bool:
        """仅已计分且没有框架错误的指标能返回通过。"""
        return self.error is None and self.score is not None and self.score >= self.threshold


class Acceptable(_Metric):
    """解析失败计零分；合法解析的动作按冻结集合精确比较。"""

    def measure(self, test_case: LLMTestCase) -> float:
        """要求实际输出与期望输出为约定 JSON；格式错误直接上抛。"""
        run = ChooseRun.model_validate_json(test_case.actual_output)
        acceptable = TypeAdapter(list[ActionMatcher]).validate_json(test_case.expected_output)
        passed = run.action is not None and matches(run.action, acceptable)
        actual = run.action.describe() if run.action is not None else run.failure
        return self._record(passed, f"动作：{actual}；期望：{test_case.expected_output}")

    @property
    def __name__(self) -> str:
        """DeepEval 汇总名称。"""
        return "acceptable"


class Parsed(_Metric):
    """重试耗尽的模型输出失败计零分，其余解析结果计一分。"""

    def measure(self, test_case: LLMTestCase) -> float:
        """按明确的运行结果计分，不从自然语言动作描述猜测解析结果。"""
        run = ChooseRun.model_validate_json(test_case.actual_output)
        return self._record(run.action is not None, run.failure or "已解析")

    @property
    def __name__(self) -> str:
        """DeepEval 汇总名称。"""
        return "parsed"


class Legal(_Metric):
    """只对已解析的动作检查原始能力掩码；解析失败不进分母。"""

    def measure(self, test_case: LLMTestCase) -> float:
        """调用方须提供原始 mask；没有动作时抛框架缺标异常。"""
        run = ChooseRun.model_validate_json(test_case.actual_output)
        if run.action is None:
            raise MissingTestCaseParamsError("解析失败，没有可检查的动作")
        metadata = test_case.metadata or {}
        space = ActionSpace(names=[], mask=metadata["mask"])
        return self._record(
            is_legal(run.action, space), f"动作 {run.action.describe()}；mask={space.mask}"
        )

    @property
    def __name__(self) -> str:
        """DeepEval 汇总名称。"""
        return "legal"


class AcceptableBy(Acceptable):
    """只把属于指定场合或标签的现场计入该组。"""

    def __init__(self, group: str, threshold: float = 1.0) -> None:
        """保存组名和阈值；组集合由数据扫描得到，不硬编码。"""
        super().__init__(threshold=threshold)
        self.group = group

    def measure(self, test_case: LLMTestCase) -> float:
        """非本组抛 MissingTestCaseParamsError，属于本组时沿用 acceptable。"""
        metadata = test_case.metadata or {}
        if metadata.get("scene") != self.group and self.group not in metadata.get("tags", []):
            raise MissingTestCaseParamsError(f"不是 {self.group} 组")
        return super().measure(test_case)

    @property
    def __name__(self) -> str:
        """DeepEval 分组汇总名称。"""
        return f"acceptable.{self.group}"


def build_metrics(cases: Sequence[ChooseCase]) -> list[BaseMetric]:
    """基础三项加数据中出现的全部场合和标签，每个组只生成一次。"""
    groups = {str(case.scene) for case in cases} | {tag for case in cases for tag in case.tags}
    return [Acceptable(), Parsed(), Legal(), *[AcceptableBy(group) for group in sorted(groups)]]
