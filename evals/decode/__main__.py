"""普通 Python 入口：DeepEval 原生帧级与字段级统计。"""

import argparse

from evals.common.run import run_evaluation

from .dataset import build_cases, select_frames
from .scorer import build_metrics


def main() -> int:
    """按选择运行 evaluate；失败返回 1，无匹配帧由 argparse 报错。"""
    parser = argparse.ArgumentParser(description="冻结帧逐字段 decode 评测")
    parser.add_argument("--frame", action="append", default=[], metavar="ID")
    parser.add_argument("--scene", metavar="NAME")
    arguments = parser.parse_args()
    try:
        frames = select_frames(arguments.frame, arguments.scene)
    except ValueError as error:
        parser.error(str(error))
    return run_evaluation(
        test_cases=build_cases(frames),
        metrics=build_metrics(select_frames()),
        results_folder="eval_results/decode",
        hyperparameters={"dataset": "frames/v2", "frames": len(frames)},
    )


if __name__ == "__main__":
    raise SystemExit(main())
