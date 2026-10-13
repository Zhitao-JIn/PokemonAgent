"""普通 Python 入口：DeepEval 原生帧级与字段级统计。"""

import argparse
import io
import os
import sys

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"

from deepeval import evaluate
from deepeval.evaluate import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
from deepeval.test_run.test_run import TestRunResultDisplay

from .dataset import build_cases, select_frames
from .scorer import build_metrics


def main() -> int:
    """按选择运行 evaluate；失败返回 1，无匹配帧由 argparse 报错。"""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="冻结帧逐字段 decode 评测")
    parser.add_argument("--frame", action="append", default=[], metavar="ID")
    parser.add_argument("--scene", metavar="NAME")
    arguments = parser.parse_args()
    try:
        frames = select_frames(arguments.frame, arguments.scene)
    except ValueError as error:
        parser.error(str(error))
    result = evaluate(
        test_cases=build_cases(frames),
        metrics=build_metrics(select_frames()),
        async_config=AsyncConfig(run_async=False),
        cache_config=CacheConfig(write_cache=False),
        error_config=ErrorConfig(skip_on_missing_params=True, ignore_errors=False),
        display_config=DisplayConfig(
            print_results=True,
            display_option=TestRunResultDisplay.FAILING,
            results_folder="eval_results/decode",
            show_indicator=False,
            inspect_after_run=False,
        ),
        hyperparameters={"dataset": "frames/v2", "frames": len(frames)},
    )
    return int(any(case.success is False for case in result.test_results))


if __name__ == "__main__":
    raise SystemExit(main())
