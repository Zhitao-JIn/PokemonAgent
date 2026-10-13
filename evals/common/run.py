"""DeepEval 原生统计与落盘；确定性指标缺标时由框架跳过。"""

import io
import os
import sys

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"

from deepeval import evaluate
from deepeval.evaluate import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from deepeval.test_run.test_run import TestRunResultDisplay


def run_evaluation(
    *,
    test_cases: list[LLMTestCase],
    metrics: list[BaseMetric],
    results_folder: str,
    hyperparameters: dict[str, str | int | float],
) -> int:
    """调用 evaluate 输出原生汇总；仅存在明确失败的用例时返回 1。

    调用方保证用例和指标已准备好；指标异常上抛，未标注字段由框架跳过。
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    result = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        async_config=AsyncConfig(run_async=False),
        cache_config=CacheConfig(write_cache=False),
        error_config=ErrorConfig(skip_on_missing_params=True, ignore_errors=False),
        display_config=DisplayConfig(
            print_results=True,
            display_option=TestRunResultDisplay.FAILING,
            results_folder=results_folder,
            show_indicator=False,
            inspect_after_run=False,
        ),
        hyperparameters=hyperparameters,
    )
    return int(any(case.success is False for case in result.test_results))
