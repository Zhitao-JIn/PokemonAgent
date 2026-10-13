"""完整目标运行的 task 装配入口。"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task

import pokemon_agent.config as config
from evals.agent_short_goal_run.bridge import samples_to_dataset
from evals.agent_short_goal_run.dataset import EvalSample, load
from evals.agent_short_goal_run.scorer import RULES
from evals.agent_short_goal_run.scorer.result_grade import result_model_scorer
from evals.agent_short_goal_run.scorer.task_scorer import e2e_scorer
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.runconfig import load_config, resolve_models
from pokemon_agent.env import load_env_file

__all__ = ["agent_short_goal_run"]


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


@task
def agent_short_goal_run(
    version: str | None = None,
    split: str | None = None,
    samples: list[str] | None = None,
    knowledge: bool | None = None,
    speed: int | None = None,
    timeout: int | None = None,
    log_dir: str | None = None,
    trace_backend: str | None = None,
    transcript: bool = True,
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

    chosen = _select(load(version, rule_ids=set(RULES)), split, sample_ids)
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
            transcript=transcript,
        ),
        scorer=[
            e2e_scorer(stall_limits=stall_limits, trace_backend=trace_backend),
            *([result_model_scorer(trace_backend, grader_model)] if grader_model else []),
        ],
        metadata={
            "dataset_version": version,
            "split": split,
            "speed": speed,
            "timeout": timeout,
            "knowledge": knowledge,
            "trace_backend": trace_backend,
            "transcript": transcript,
            "models": models,
            "stall_limits": list(stall_limits),
            "sample_ids": [s.sample_id for s in chosen],
        },
    )
