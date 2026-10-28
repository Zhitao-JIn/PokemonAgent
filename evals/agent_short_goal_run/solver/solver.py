"""solver 侧薄适配：被测对象槽位（spec2 §四取舍 A）。

`run_one_solver` 是真实现：把请求交给 worker **子进程**跑完一条样本（模拟器崩溃不连累
别的样本）→ 产物落 `runs/<样本[#e<n>]>` → 把 `run_result.json` 的文本放进 solver 输出，
scorer 据此与 trace 打分。epochs 的圈号从 `state.epoch` 取。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

from inspect_ai.event import InfoEvent
from inspect_ai.log._transcript import transcript as sample_transcript
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.scorer.stream import RunStream
from evals.agent_short_goal_run.solver.record import AgentRunRecord, RunOneRecord, RunOneRequest
from evals.agent_short_goal_run.solver.runner.one import run_id_for
from evals.agent_short_goal_run.solver.transcript import replay_into_transcript
from evals.common.eval_services import eval_services
from evals.paths import REPO_ROOT

__all__ = ["Generate", "Solver", "TaskState", "run_id_for", "run_one_solver", "solver"]


def work_dir_of(report_dir: str | Path, sample_id: str, epoch: int) -> Path:
    """一条样本一个 epoch 的工作目录（run_one / scorer 共用同一命名）。"""
    return Path(report_dir) / "runs" / (sample_id if epoch == 1 else f"{sample_id}#e{epoch}")


def _finish(
    state: TaskState,
    work: Path,
    run_id: str,
    backend: str,
    replay: bool,
    models: dict[str, str],
    invalid: str = "",
) -> TaskState:
    """读取子进程交接文件并写 store；无效或超时不回放。"""
    record_file = work / "run.json"
    record = store_as(AgentRunRecord)
    if record_file.is_file() and not invalid:
        saved = RunOneRecord.model_validate_json(record_file.read_text(encoding="utf-8"))
        record.run_id, record.branch = saved.run_id, saved.branch
        record.invalid, record.error = saved.invalid, saved.error
    else:
        record.run_id = run_id
        record.invalid = invalid or "run-one 未生成 run.json"
    record.work_dir = str(work)
    result_file = work / "run_result.json"
    record.run_result = result_file.read_text(encoding="utf-8") if result_file.is_file() else ""
    state.output.completion = "timeout" if invalid == "timeout" else record.run_result
    if replay:
        if record.invalid:
            sample_transcript()._event(
                InfoEvent(
                    source="agent_short_goal_run",
                    data={"invalid": record.invalid, "error": record.error},
                )
            )
        else:
            stream = RunStream.load(
                work / "trace", record.run_id, branch=record.branch or None, backend=backend
            )
            replay_into_transcript(stream, models)
    return state


@solver
def run_one_solver(
    *,
    report_dir: str,
    run_config_path: str,
    models: dict[str, str],
    timeout: int,
    trace_backend: str = "local",
    version: str = "v1",
    transcript: bool = True,
    ignore_initial_memory: bool = False,
    export_memory_dir: str | None = None,
) -> Solver:
    """被测对象槽位：起 worker 子进程跑完一条样本。

    前置条件：`state.metadata["sample_id"]` 已由 bridge 写入；子进程从仓库根起跑
    （run_one 的断言）。失败：单样本超时 → `completion="timeout"`（记 unjudgeable 的形状，
    不抛——与旧 batch 的"超时即杀、该条记无效"同口径）。
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sample_id = str(state.metadata["sample_id"])
        sample = next(item for item in load_samples(version) if item.sample_id == sample_id)
        epoch = int(state.epoch)
        work = work_dir_of(report_dir, sample_id, epoch)
        request = RunOneRequest(
            work_dir=str(work),
            run_config_path=run_config_path,
            sample_id=sample_id,
            epoch=epoch,
            models=models,
            trace_backend=trace_backend,
            version=version,
        )
        service_options: dict[str, object] = {
            "world": True,
            "memory": True,
            "knowledge_source": REPO_ROOT / "memory" / "knowledge_memory",
            "admin": True,
            "export_env": False,
        }
        if sample.initial_memory is not None and not ignore_initial_memory:
            service_options["memory_seed"] = (
                REPO_ROOT
                / "evals"
                / "agent_short_goal_run"
                / "dataset"
                / version
                / sample.initial_memory.path
            )
        if sample.knowledge_exclude_topics:
            service_options["knowledge_exclude_topics"] = sample.knowledge_exclude_topics
        if export_memory_dir:
            service_options["export_memory_to"] = Path(export_memory_dir) / (
                sample_id if epoch == 1 else f"{sample_id}#e{epoch}"
            )
        cmd = [sys.executable, "-m", "evals.agent_short_goal_run.solver.worker"]
        stack = ExitStack()
        entering = asyncio.create_task(
            asyncio.to_thread(
                stack.enter_context,
                eval_services(**service_options),
            )
        )
        entered = False
        try:
            service_environment = await asyncio.shield(entering)
            entered = True
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                input=request.model_dump_json().encode(),
                cwd=str(REPO_ROOT),
                timeout=timeout,
                check=False,
                env={**os.environ, **service_environment},
            )
        except subprocess.TimeoutExpired:
            return _finish(
                state,
                work,
                run_id_for(sample_id, epoch),
                trace_backend,
                transcript,
                models,
                invalid="timeout",
            )
        except asyncio.CancelledError:
            if not entered:
                try:
                    await asyncio.shield(entering)
                    entered = True
                except BaseException:
                    pass
            raise
        finally:
            if entered:
                await asyncio.shield(asyncio.to_thread(stack.close))
        return _finish(state, work, run_id_for(sample_id, epoch), trace_backend, transcript, models)

    return solve
