"""真实模拟器脚本评测，默认串行，每个用例有 300 秒进程保护。"""

import argparse

from evals.common.run import run_evaluation

from .dataset import load
from .dataset.cases import build_cases
from .scorer import ScriptPass, ScriptSide


def main() -> int:
    """按 case/script 取交集；未知选择或非正 workers 报参数错误。"""
    parser = argparse.ArgumentParser(description="脚本自报与世界真值评测")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--script", action="append", default=[])
    parser.add_argument("--version", default="v1")
    parser.add_argument("--workers", type=int, default=1)
    arguments = parser.parse_args()
    cases = load(arguments.version)
    if not set(arguments.case) <= {case.case_id for case in cases}:
        parser.error(f"未知用例：{arguments.case}")
    if not set(arguments.script) <= {case.script for case in cases}:
        parser.error(f"未知脚本：{arguments.script}")
    if arguments.workers < 1:
        parser.error("workers 必须为正")
    selected = [
        case
        for case in cases
        if (not arguments.case or case.case_id in arguments.case)
        and (not arguments.script or case.script in arguments.script)
    ]
    if not selected:
        parser.error("没有符合筛选条件的用例")
    return run_evaluation(
        test_cases=build_cases(selected, arguments.version, arguments.workers),
        metrics=[
            ScriptSide("code"),
            ScriptSide("truth"),
            *[ScriptPass(script) for script in sorted({case.script for case in cases})],
        ],
        results_folder="eval_results/world_script_execute",
        hyperparameters={"dataset": arguments.version, "workers": arguments.workers},
    )


if __name__ == "__main__":
    raise SystemExit(main())
