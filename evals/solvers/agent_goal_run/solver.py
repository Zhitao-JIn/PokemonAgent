"""solver 侧薄适配：被测对象槽位（spec2 §四取舍 A）。

`run_one_solver` 是真实现：拼 run-one 命令 → **子进程**跑完一条样本（模拟器崩溃不连累
别的样本）→ 产物落 `runs/<样本[#e<n>]>` → 把 `run_result.json` 的文本放进 solver 输出，
scorer 据此与 trace 打分。epochs 的圈号从 `state.epoch` 取。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from inspect_ai.solver import Generate, Solver, TaskState, solver

from evals.data import REPO_ROOT
from evals.solvers.agent_goal_run.runner.one import run_id_for

__all__ = ["Generate", "Solver", "TaskState", "run_id_for", "run_one_solver", "solver"]


def work_dir_of(report_dir: str | Path, sample_id: str, epoch: int) -> Path:
    """一条样本一个 epoch 的工作目录（run_one / scorer 共用同一命名）。"""
    return Path(report_dir) / "runs" / (sample_id if epoch == 1 else f"{sample_id}#e{epoch}")


@solver
def run_one_solver(
    *,
    report_dir: str,
    models: dict[str, str],
    knowledge: bool,
    speed: int,
    timeout: int,
    trace_backend: str = "local",
    version: str = "v1",
) -> Solver:
    """被测对象槽位：起 run-one 子进程跑完一条样本。

    前置条件：`state.metadata["sample_id"]` 已由 bridge 写入；子进程从仓库根起跑
    （run_one 的断言）。失败：单样本超时 → `completion="timeout"`（记 unjudgeable 的形状，
    不抛——与旧 batch 的"超时即杀、该条记无效"同口径）。
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sample_id = str(state.metadata["sample_id"])
        epoch = int(state.epoch)
        work = work_dir_of(report_dir, sample_id, epoch)
        cmd = [
            sys.executable, "-m", "evals", "agent_goal_run", "run-one",
            "--report-dir", report_dir, "--sample", sample_id, "--epoch", str(epoch),
            "--speed", str(speed), *(["--no-knowledge"] if not knowledge else []),
            "--trace-backend", trace_backend, "--version", version,
            *[a for k, v in models.items() for a in (f"--{k.replace('_', '-')}", v)],
        ]  # fmt: skip
        try:
            await asyncio.to_thread(
                subprocess.run, cmd, cwd=str(REPO_ROOT), timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            state.output.completion = "timeout"
            return state
        result_file = work / "run_result.json"
        state.output.completion = (
            result_file.read_text(encoding="utf-8") if result_file.is_file() else ""
        )
        return state

    return solve
