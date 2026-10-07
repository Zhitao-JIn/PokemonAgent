"""列六个 task、交 inspect 跑测评，以及数据构建与内部 run-one 入口。"""

import subprocess
import sys

from evals.tasks.registry import TASKS


def main(argv: list[str] | None = None) -> int:
    """run 参数原样交 inspect；旧独立宏与视图测评入口不再开放。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["list"]:
        for name, path in TASKS.items():
            print(f"{name}\t{path}")
        return 0
    if len(args) >= 2 and args[0] == "run" and args[1] in TASKS:
        return subprocess.run(
            [sys.executable, "-m", "inspect_ai", "eval", TASKS[args[1]], *args[2:]], check=False
        ).returncode
    if args == ["freeze-frames"]:
        from evals.dataset.frames.build.freeze import freeze_takeover
        from evals.dataset.frames.build.terrain import freeze_terrain

        freeze_takeover()
        freeze_terrain()
        return 0
    if args[:2] == ["agent_goal_run", "run-one"]:
        from evals.solvers.agent_goal_run.cli import main as run_one_main

        return run_one_main(args[1:])
    if args[:2] == ["frames", "build"]:
        from evals.dataset.frames.build.cli import main as build_main

        return build_main(args[1:])
    usage = "用法：python -m evals list | run <task> [inspect 参数] | freeze-frames | frames build"
    print(usage, file=sys.stderr)
    return 2
