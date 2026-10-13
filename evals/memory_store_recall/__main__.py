"""普通 Python 入口：真实写入读回与检索，原生逐指标统计。"""

import argparse

from evals.common.run import run_evaluation

from .dataset import build_cases, load
from .scorer import RecallAtK, ReciprocalRank, StorageMatch
from .solver import run_memory


def main() -> int:
    """执行一次隔离冻结库评测；k 非正时报参数错误。"""
    parser = argparse.ArgumentParser(description="冻结记忆存储与召回评测")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--version", default="v1")
    arguments = parser.parse_args()
    if arguments.k < 1:
        parser.error("k 必须为正")
    [dataset] = load(arguments.version)
    run = run_memory(dataset, arguments.k)
    return run_evaluation(
        test_cases=build_cases(dataset, run.storage_problems, run.retrieved),
        metrics=[StorageMatch(), RecallAtK(arguments.k), ReciprocalRank(arguments.k)],
        results_folder="eval_results/memory_store_recall",
        hyperparameters={"dataset": arguments.version, "k": arguments.k},
    )


if __name__ == "__main__":
    raise SystemExit(main())
