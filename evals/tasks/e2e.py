"""e2e 测评的 task 家（spec2 §二）：`inspect eval evals/tasks/e2e.py` 的入口（R3，0929 修订）。

数据流（spec2 §三）：`data/v1` 冻结样本 → bridge 翻译成 inspect 数据集 → solver 起
run-one 子进程（真机，PyBoy + 被测链路）→ scorer 读子进程落下的 trace 打分（统一
Scorer：机械 + 红线）→ inspect 出 accuracy / stderr / Epochs reducer 指标 → `.eval` 落
`log_dir`。`inspect view --log-dir <log_dir>` 看结果，metadata 里的 run_id 去 Langfuse
看过程。

**参数只认 `evals/config.json`**（不自研 CLI，0929 用户定向）：task 函数参数缺省
`None` → 回退配置值；`inspect eval -T key=value` 逐项覆盖；epochs / log-dir 本身是
`inspect eval` 自带旗标。真机跑批交用户本机（二号条）。
"""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    Score,
    Scorer,
    Target,
    scorer,
)
from inspect_ai.solver import TaskState

import pokemon_agent.config as config
from evals.bridge import samples_to_dataset
from evals.core import mechanical_scorer, red_line_scorer
from evals.core.judged import judged_accuracy, judged_count
from evals.core.solver import run_one_solver, work_dir_of
from evals.data import check, load_samples
from evals.e2e.runner.one import run_id_for
from evals.runconfig import load_config, resolve_models
from evals.schema import EvalSample
from evals.scorers import RULES, RunStream
from evals.tasks.result_grade import result_model_scorer
from pokemon_agent.env import load_env_file

__all__ = ["e2e", "e2e_scorer"]


def _select(
    samples: list[EvalSample], split: str | None, ids: list[str] | None
) -> list[EvalSample]:
    """按切分与 id 过滤（给了 id 就只跑这些，顺序照数据集）。"""
    chosen = [s for s in samples if split is None or s.split == split]
    if ids:
        missing = set(ids) - {s.sample_id for s in chosen}
        assert not missing, f"数据集里没有这些样本：{sorted(missing)}"
        chosen = [s for s in chosen if s.sample_id in ids]
    return chosen


@scorer(metrics=[judged_accuracy(), judged_count()])
def e2e_scorer(
    *, report_dir: str, stall_limits: tuple[int, int], trace_backend: str = "local"
) -> Scorer:
    """e2e 的判定 scorer：统一 Scorer（机械 + 红线）→ inspect `Score`。

    真值口径不变：机械判定第一真源，红线命中即判负；value 用 inspect 的
    CORRECT / INCORRECT / NOANSWER 字面量（unjudgeable = NOANSWER）。证据 uuid 与
    run_id 进 metadata——View 钻取 ↔ Langfuse 定位的接线点。
    `stall_limits` 由 task 装配期从 `pokemon_agent.config` 快照进闭包（不读 live config）。
    `trace_backend` 与 run-one 的写账后端同源（langfuse 时 scorer 直问服务）。
    """

    async def score(state: TaskState, target: Target) -> Score:
        del target  # 机械真值在游戏内存里，不在数据集 target 上
        sample_id = str(state.metadata["sample_id"])
        epoch = int(state.epoch)
        sample = next(
            s
            for s in load_samples(str(state.metadata["dataset_version"]))
            if s.sample_id == sample_id
        )
        run_id = run_id_for(sample_id, epoch)
        work = work_dir_of(report_dir, sample_id, epoch)
        branch = None
        record_file = work / "run.json"
        if record_file.is_file():
            record = json.loads(record_file.read_text(encoding="utf-8"))
            if record.get("invalid"):
                return Score(
                    value=NOANSWER,
                    explanation=f"run-one 记为无效：{record['invalid']}",
                    metadata={"run_id": run_id, "sample_id": sample_id, "epoch": epoch},
                )
            # langfuse 后端按 (run_id, branch) 寻址——branch 由 run-one 收尾写进 run.json。
            branch = record.get("branch") or None
        stream = RunStream.load(work / "trace", run_id, branch=branch, backend=trace_backend)
        mech = mechanical_scorer()(stream, sample)
        line = red_line_scorer(*stall_limits)(stream, sample)
        if line.outcome == "fail":
            value, explanation = INCORRECT, f"红线：{line.reason}"
        elif mech.outcome == "pass":
            value, explanation = CORRECT, mech.reason
        elif mech.outcome == "fail":
            value, explanation = INCORRECT, mech.reason
        else:
            value, explanation = NOANSWER, mech.reason or "不可机械判定"
        return Score(
            value=value,
            explanation=explanation,
            metadata={
                "run_id": run_id,
                "sample_id": sample_id,
                "epoch": epoch,
                "mech_outcome": mech.outcome,
                "red_line_outcome": line.outcome,
                "evidence": mech.evidence,
            },
        )

    return score


@task
def e2e(
    version: str | None = None,
    split: str | None = None,
    samples: list[str] | None = None,
    knowledge: bool | None = None,
    speed: int | None = None,
    timeout: int | None = None,
    log_dir: str | None = None,
    trace_backend: str | None = None,
    grader_model: str | None = "openai-api/deepseek/deepseek-flash",
) -> Task:
    """e2e 测评：dataset + solver + scorer（指标挂 scorer，epochs 走 `inspect eval --epochs`）。

    参数缺省读 `evals/config.json`（`runconfig.load_config`）；`inspect eval -T` 逐项
    覆盖。`log_dir` 是 run-one 产物（`runs/<样本[#e<n>]>`）的落盘根——建议与
    `inspect eval --log-dir` 同值，`.eval` 与 trace 同根。被测系统的红线阈值
    （`config.EPISODE_STALL_LIMIT` / `RUN_STALL_LIMIT`）在装配期快照进 scorer 闭包。
    `trace_backend`（local/langfuse）是**写账与读账共同的后端**：run-one 用它写，
    scorer 用它读——切换前先确认对应服务可用（langfuse 需本机服务在跑）。
    """
    cfg = load_config()
    load_env_file()
    import os

    os.environ.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    version = version or str(cfg["version"])
    split = split if split is not None else (str(cfg["split"]) if cfg["split"] else None)
    sample_ids = samples if samples is not None else [str(s) for s in cfg.get("samples", [])]
    knowledge = knowledge if knowledge is not None else bool(cfg["knowledge"])
    speed = speed if speed is not None else int(cfg["speed"])
    timeout = timeout if timeout is not None else int(cfg["timeout"])
    report_dir = log_dir or str(cfg["log_dir"])
    trace_backend = trace_backend or str(cfg.get("trace_backend", "local"))
    models = resolve_models(cfg.get("models", {}))
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    chosen = _select(check(version, set(RULES)), split, sample_ids)
    stall_limits = (config.EPISODE_STALL_LIMIT, config.RUN_STALL_LIMIT)
    return Task(
        dataset=samples_to_dataset(chosen),
        solver=run_one_solver(
            report_dir=report_dir,
            models=models,
            knowledge=knowledge,
            speed=speed,
            timeout=timeout,
            trace_backend=trace_backend,
            version=version,
        ),
        scorer=[
            e2e_scorer(
                report_dir=report_dir, stall_limits=stall_limits, trace_backend=trace_backend
            ),
            *(
                [result_model_scorer(report_dir, trace_backend, grader_model)]
                if grader_model
                else []
            ),
        ],
        metadata={
            "dataset_version": version,
            "split": split,
            "speed": speed,
            "timeout": timeout,
            "knowledge": knowledge,
            "trace_backend": trace_backend,
            "models": models,
            "stall_limits": list(stall_limits),
            "sample_ids": [s.sample_id for s in chosen],
        },
    )
