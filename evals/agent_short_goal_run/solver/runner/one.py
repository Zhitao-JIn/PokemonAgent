"""跑一条样本（在独立子进程里，工作目录 = 仓库根）：直读打包好的起点存档 → 恢复 → 跑完一个 run。

只落盘、不判定。工作目录 `runs/<sample_id>[#e<n>]/` 下放本条样本独立的
`trace/`、`memory/`、`checkpoints/`，最后写 `run.json`（`run_id`、`invalid`、`error`）
与 `run_result.json`（`RunResult`，V8）。
起点存档缺失或被拒载记 `invalid`（先跑
`python -m evals.agent_short_goal_run.dataset.build.pack` 重打），
run 自己出错只记 `error`——它是被测系统的问题，由红线 R1 判。

评测前置（本机跑评测前先满足）：①world server 已起（带或不带 `--state-file` 均可，
`--watch`/`--speed` 在 server 命令行设置）；②memory server 已起并带 `--enable-admin`，
且是评测专用实例（pack 与 memory_store_recall 会清空它，restore 会覆盖它）；
③设好两个环境变量 `MCP_WORLD_SERVER_URL`、`MCP_MEMORY_SERVER_URL`
（评测进程把它们写进每条样本的覆盖文件，被测系统本身只读配置）；④评测串行。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.common.overlay import sample_overlay, write_overlay
from evals.paths import REPO_ROOT
from pokemon_agent.build import build_real
from pokemon_agent.env import load_env_file
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.checkpoint import CheckpointIncompatible, restore_run

from .archive import prepare_archive

RUN_RECORD = "run.json"
RUN_RESULT = "run_result.json"


def run_one(
    sample: EvalSample,
    work: Path,
    *,
    run_config_path: str,
    epoch: int = 1,
) -> None:
    """跑一条样本并写 `run.json`。前置条件：当前工作目录是仓库根（存档清单里的路径相对它）。

    `epoch`：第几次重复（V2）。>1 时 run_id 加 `#e{n}` 后缀、调用方给独立工作目录——
    同一样本的各 epoch 互不残留（R3 的 eval_set 按 epoch 起子进程）。
    `run_config_path`：task 落盘的 settings 覆盖层（预算、型号、trace 后端——后端与 scorer
    的读账后端同源，langfuse 需本机服务在跑）；与本条样本的覆盖层一起交给唯一装配点。
    """
    assert Path.cwd().resolve() == REPO_ROOT.resolve(), "run_one 要从仓库根起跑"
    assert epoch >= 1, "epoch 从 1 起"
    load_env_file(REPO_ROOT / ".env")
    work.mkdir(parents=True, exist_ok=True)

    # 步骤 1：起点——直读数据层里**打包好的** run 级存档（打包是数据准备动作，见 data/pack.py）。
    run_id = run_id_for(sample.sample_id, epoch)
    manifest = (
        DATASET_DIR / sample.dataset_version / "archives" / sample.start.archive / "manifest.json"
    )
    if not manifest.is_file():
        _record(
            work,
            run_id,
            invalid=(
                f"起点存档缺失：{manifest}"
                "（python -m evals.agent_short_goal_run.dataset.build.pack 重打）"
            ),
        )
        return

    # 步骤 2：从存档恢复出新执行线，跑到 run 结束。
    def build_branch(branch: str) -> RunRuntime:
        sample_config, _digest = write_overlay(
            work / f"config-{branch}.json", sample_overlay(run_id=run_id, branch=branch, work=work)
        )
        harness, _game = build_real(config=[run_config_path, sample_config])
        return harness.deps

    try:
        manifest = prepare_archive(sample, work / "start")
        result = restore_run(manifest, build_branch, sample_id=sample.sample_id)
        (work / RUN_RESULT).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except CheckpointIncompatible as exc:
        _record(work, run_id, invalid=f"存档拒载：{exc}")
        return
    except Exception as exc:  # noqa: BLE001 —— run 自己出错照样收尾，交给红线 R1
        _record(work, run_id, error=f"{type(exc).__name__}: {exc}")
        return
    _record(work, run_id, branch=result.branch)


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


__all__ = ["run_id_for", "run_one"]
