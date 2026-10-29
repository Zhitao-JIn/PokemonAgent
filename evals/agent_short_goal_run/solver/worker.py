"""solver 的单样本子进程本体：从 stdin 读一份 `RunOneRequest`，跑完一条样本并落盘。

只有 `solver.run_one_solver` 会启动它（`python -m evals.agent_short_goal_run.solver.worker`），
请求模型与 solver 同包共用——没有命令行、没有开关。独立子进程的目的：模拟器崩溃不连累别的样本。
"""

from __future__ import annotations

import sys
from pathlib import Path

from evals.agent_short_goal_run.dataset import load as load_samples
from evals.agent_short_goal_run.solver.record import RunOneRequest
from evals.dataset.errors import DatasetError


def main() -> int:
    """读 stdin 的请求并执行，返回退出码；数据集有问题返回 2。"""
    request = RunOneRequest.model_validate_json(sys.stdin.buffer.read())
    try:
        _execute(request)
    except DatasetError as exc:
        print(f"数据集有问题：\n{exc}", file=sys.stderr)
        return 2
    return 0


def _execute(request: RunOneRequest) -> None:
    """按请求跑一条样本。"""
    from evals.agent_short_goal_run.solver.runner import run_one

    [sample] = [s for s in load_samples(request.version) if s.sample_id == request.sample_id]
    run_one(
        sample,
        Path(request.work_dir),
        run_config_path=request.run_config_path,
        epoch=request.epoch,
        effective_budget=request.effective_budget,
    )


__all__ = ["main"]


if __name__ == "__main__":
    sys.exit(main())
