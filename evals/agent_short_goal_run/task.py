"""完整目标运行的 task 装配入口。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from inspect_ai import Task, task

from evals.agent_short_goal_run.bridge import samples_to_dataset
from evals.agent_short_goal_run.dataset import EvalSample, load
from evals.agent_short_goal_run.scorer import RULES
from evals.agent_short_goal_run.scorer.cost_scorer import success_cost_scorer
from evals.agent_short_goal_run.scorer.decision_scorer import decision_actions_scorer
from evals.agent_short_goal_run.scorer.duration_scorer import run_duration_scorer
from evals.agent_short_goal_run.scorer.model_calls_scorer import model_calls_scorer
from evals.agent_short_goal_run.scorer.movement_scorer import movement_steps_scorer
from evals.agent_short_goal_run.scorer.overshoot_scorer import post_completion_actions_scorer
from evals.agent_short_goal_run.scorer.repeat_scorer import ineffective_repetition_scorer
from evals.agent_short_goal_run.scorer.result_grade import result_model_scorer
from evals.agent_short_goal_run.scorer.task_scorer import e2e_scorer
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.common.overlay import eval_overlay, write_overlay
from evals.runconfig import (
    ResultGraderConfig,
    load_config,
    resolve_models,
    resolve_result_grader,
    validate_grader_independence,
)
from pokemon_agent.env import load_env_file
from pokemon_agent.settings import load_config as load_app_config

__all__ = ["agent_short_goal_run", "write_run_config"]


def write_run_config(report_dir: str | Path, overlay: Mapping[str, object]) -> tuple[Path, str]:
    """将本次评测的 settings 覆盖层落成唯一文件，并在派 worker 前验证它能与保底合并。"""
    path, digest = write_overlay(Path(report_dir).resolve() / "run_config.json", overlay)
    load_app_config(path)
    return path, digest


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


def _result_grader(
    evaluation_models: Mapping[str, object], models: Mapping[str, str], grader_model: str | None
) -> ResultGraderConfig | None:
    """缺省读取完整配置；none 关闭，其他覆盖型号并在装配期检查独立性。"""
    grader = resolve_result_grader(evaluation_models)
    if grader_model is not None and grader_model.lower() == "none":
        return None
    if grader_model is not None:
        grader = ResultGraderConfig.model_validate({**grader.model_dump(), "model": grader_model})
    validate_grader_independence(grader, models)
    return grader


@task
def agent_short_goal_run(
    version: str | None = None,
    split: str | None = None,
    samples: list[str] | None = None,
    timeout: int | None = None,
    log_dir: str | None = None,
    trace_backend: str | None = None,
    transcript: bool = True,
    grader_model: str | None = None,
) -> Task:
    """e2e 测评：dataset + solver + scorer（指标挂 scorer，epochs 走 `inspect eval --epochs`）。

    `grader_model=None` 使用配置，字符串 none 关闭独立评分，其他字符串只覆盖型号。
    参数缺省读 `evals/config.json`（`runconfig.load_config`）；`inspect eval -T` 逐项
    覆盖。`log_dir` 是 run-one 产物（`runs/<样本[#e<n>]>`）的落盘根——建议与
    `inspect eval --log-dir` 同值，`.eval` 与 trace 同根。被测系统的红线阈值
    （生效配置的 `loop.episode_stall` / `loop.run_stall`）在装配期快照进 scorer 闭包。
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
    timeout = timeout if timeout is not None else int(cfg["timeout"])
    report_dir = log_dir or str(cfg["log_dir"])
    trace_backend = trace_backend or str(cfg.get("trace_backend", "local"))
    models = resolve_models(cfg.get("models", {}))
    grader = _result_grader(cfg["evaluation_models"], models, grader_model)
    chosen = _select(load(version, rule_ids=set(RULES)), split, sample_ids)
    overlay = eval_overlay({**cfg, "trace_backend": trace_backend})
    run_config_path, run_config_sha256 = write_run_config(report_dir, overlay)
    app_config = load_app_config(run_config_path).config
    (run_config_path.parent / "baseline_context.json").write_text(
        json.dumps(
            {
                "run_config_path": str(run_config_path),
                "run_config_sha256": run_config_sha256,
                "models": models,
                "sample_ids": [s.sample_id for s in chosen],
                "timeout": timeout,
                "trace_backend": trace_backend,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stall_limits = (app_config.loop.episode_stall_limit, app_config.loop.run_stall_limit)
    return Task(
        dataset=samples_to_dataset(chosen),
        solver=run_one_solver(
            report_dir=report_dir,
            run_config_path=str(run_config_path),
            models=models,
            timeout=timeout,
            trace_backend=trace_backend,
            version=version,
            transcript=transcript,
        ),
        scorer=[
            e2e_scorer(stall_limits=stall_limits, trace_backend=trace_backend),
            movement_steps_scorer(trace_backend, stall_limits),
            decision_actions_scorer(trace_backend, stall_limits),
            ineffective_repetition_scorer(trace_backend, stall_limits),
            post_completion_actions_scorer(trace_backend, stall_limits),
            model_calls_scorer(trace_backend, stall_limits),
            run_duration_scorer(trace_backend, stall_limits),
            success_cost_scorer(trace_backend, stall_limits),
            *([result_model_scorer(trace_backend, grader)] if grader is not None else []),
        ],
        metadata={
            "dataset_version": version,
            "split": split,
            "timeout": timeout,
            "trace_backend": trace_backend,
            "transcript": transcript,
            "models": models,
            "stall_limits": list(stall_limits),
            "sample_ids": [s.sample_id for s in chosen],
            "run_config_path": str(run_config_path),
            "run_config_sha256": run_config_sha256,
        },
    )
