"""跑一条样本（在独立子进程里，工作目录 = 仓库根）：加载原始 `.state` → 跑完一个 run。

只落盘、不判定。工作目录 `runs/<sample_id>[#e<n>]/` 下放本条样本独立的
`trace/`、`memory/`、`checkpoints/`，最后写 `run.json`（`run_id`、`invalid`、`error`）
与 `run_result.json`（`RunResult`，V8）。
起点校验不通过记 `invalid`，run 自己出错只记 `error`——它是被测系统的问题，由红线 R1 判。

评测 solver 会为每条样本启动独立 world 与 memory 服务，并复制仓库 knowledge；若设置了
`MCP_WORLD_SERVER_URL` 或 `MCP_MEMORY_SERVER_URL`，对应服务会复用已有地址（调试用）。
该样本结束后服务随之关闭。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.failure import exception_leaves
from evals.common.overlay import sample_overlay, write_overlay
from evals.dataset.errors import DatasetError
from evals.paths import REPO_ROOT
from pokemon_agent.brain import Goal, Task
from pokemon_agent.build import build_real
from pokemon_agent.env import load_env_file
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToGameToolResetReq,
)

RUN_RECORD = "run.json"
RUN_RESULT = "run_result.json"


def run_one(sample: EvalSample, work: Path, *, run_config_path: str, epoch: int = 1) -> None:
    """跑一条样本并写 `run.json`。前置条件：当前工作目录是仓库根。
    `epoch` 从 1 起；>1 时 run_id 加 `#e{n}`，调用方须提供独立工作目录。
    `run_config_path` 是预算、型号及 trace 后端覆盖层，与样本覆盖层一起交给装配点。
    """
    assert Path.cwd().resolve() == REPO_ROOT.resolve(), "run_one 要从仓库根起跑"
    assert epoch >= 1, "epoch 从 1 起"
    load_env_file(REPO_ROOT / ".env")
    work.mkdir(parents=True, exist_ok=True)

    run_id = run_id_for(sample.sample_id, epoch)
    branch = "main"
    sample_config, _digest = write_overlay(
        work / f"config-{branch}.json", sample_overlay(run_id=run_id, branch=branch, work=work)
    )
    game = None
    stage = "build"
    try:
        harness, game = build_real(config=[run_config_path, sample_config])
        start_task = _task_for(sample)
        stage = "start_state"
        state_path = DATASET_DIR / sample.dataset_version / sample.start.source_state
        game.use_start_state(state_path)
        if sample.check_id in {"party_healed", "shop_cancelled"}:
            stage = "preflight_reset"
            game.reset(FromHarnessToGameToolResetReq(task=start_task))
            stage = "preflight_perceive"
            perceived = game.perceive_task()
            stage = "start_validation"
            if not _valid_start(sample, perceived, work, run_id):
                return
        stage = "harness_run"
        # 空目标表 + 显式 run goal：执行目标全部由 run planner 建，样本 id 不再当目标 id。
        # `start_task` 只给世界 reset 用（样本的 `initial_state_hint` 经它带进去）。
        result = harness.run(
            run_id,
            [],
            run_goal=Goal(goal=sample.goal, criteria=sample.success_criteria),
            start_task=start_task,
            sample_id=sample.sample_id,
        )
        stage = "write_result"
        (work / RUN_RESULT).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 —— 运行错误保留给红线 R1
        leaves = json.dumps(
            [leaf.model_dump() for leaf in exception_leaves(exc)], ensure_ascii=False
        )
        _record(work, run_id, error=f"stage={stage}; {type(exc).__name__}: {exc}; leaves={leaves}")
        return
    finally:
        if game is not None:
            game.release_lease()
    _record(work, run_id, branch=result.branch)


def _task_for(sample: EvalSample) -> Task:
    """起点校验与正式 run 的 reset 共用同一个引导任务（它不是任何一局的执行目标）。"""
    return Task(
        task_id=sample.sample_id,
        goal=sample.goal,
        success_criteria=sample.success_criteria,
        max_steps=sample.max_steps,
        initial_state_hint=sample.initial_state_hint,
    )


def _valid_start(
    sample: EvalSample, perceived: FromHarnessToGameToolPerceiveTaskResp, work: Path, run_id: str
) -> bool:
    """原样执行起点判据；数据不合格只记 invalid，不进入正式 run。"""
    try:
        validate_start(sample, perceived.ram, perceived.observation)
    except DatasetError as exc:
        _record(work, run_id, invalid=f"{sample.sample_id}（{sample.check_id}）：{exc}")
        return False
    return True


def run_id_for(sample_id: str, epoch: int = 1) -> str:
    """一条样本一个 epoch 的 run_id：`eval-<sample_id>`，epochs>1 时加 `#e<n>` 后缀。"""
    assert epoch >= 1, "epoch 从 1 起"
    return f"eval-{sample_id}" if epoch == 1 else f"eval-{sample_id}#e{epoch}"


def _record(
    work: Path, run_id: str, *, invalid: str = "", error: str = "", branch: str = ""
) -> None:
    """写本条样本的批跑小结。`branch` 给 scorer 定位 langfuse trace（按 branch 寻址）。"""
    payload = {"run_id": run_id, "invalid": invalid, "error": error, "branch": branch}
    (work / RUN_RECORD).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if invalid or error:
        print(f"{run_id}: {invalid or error}", file=sys.stderr)


__all__ = ["run_id_for", "run_one"]
