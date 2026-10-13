"""按用例种类挂指标，DeepEval 原生统计逐记录与逐查询分数。"""

import json

from deepeval.errors import MissingTestCaseParamsError
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .compare import retrieval_metrics


class StorageMatch(BaseMetric):
    """仅计存储记录，问题清单为空才通过。"""

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_model = None

    def measure(self, test_case: LLMTestCase) -> float:
        """非 store 用例跳过；非法 JSON 上抛。"""
        if (test_case.additional_metadata or {}).get("kind") != "store":
            raise MissingTestCaseParamsError("不是存储用例")
        problems = json.loads(test_case.actual_output)["problems"]
        self.score = 0.0 if problems else 1.0
        self.reason = "；".join(problems) or "存储读回符合"
        return self.score

    @property
    def __name__(self) -> str:
        """原生汇总列名。"""
        return "storage"


class RecallAtK(BaseMetric):
    """前 k 条中召回的相关记录比例。"""

    def __init__(self, k: int, threshold: float = 1.0) -> None:
        self.k = k
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_model = None

    def measure(self, test_case: LLMTestCase) -> float:
        """非 query 用例跳过；期望相关列表必须非空。"""
        if (test_case.additional_metadata or {}).get("kind") != "query":
            raise MissingTestCaseParamsError("不是检索用例")
        recall, rank = retrieval_metrics(
            json.loads(test_case.actual_output), json.loads(test_case.expected_output), self.k
        )
        self.score = rank if self.__name__ == "mrr" else recall
        self.reason = f"{self.__name__}={self.score}"
        return self.score

    @property
    def __name__(self) -> str:
        """原生汇总列名。"""
        return "recall_at_k"


class ReciprocalRank(RecallAtK):
    """前 k 条中第一条相关记录的倒数排名，无命中为 0。"""

    @property
    def __name__(self) -> str:
        """原生汇总列名。"""
        return "mrr"
