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
③设好两个环境变量 `MCP_WORLD_SERVER_URL`、`MCP_MEMORY_SERVER_URL`；④评测串行。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from evals.agent_short_goal_run.dataset.loader import DATASET_DIR
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.paths import REPO_ROOT
from pokemon_agent.build import build_real
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.checkpoint import CheckpointIncompatible, restore_run

from .archive import prepare_archive

RUN_RECORD = "run.json"
RUN_RESULT = "run_result.json"


def run_one(
    sample: EvalSample,
    work: Path,
    models: dict[str, str],
    *,
    run_config_path: str,
    epoch: int = 1,
    trace_backend: str = "local",
) -> None:
    """跑一条样本并写 `run.json`。前置条件：当前工作目录是仓库根（存档清单里的路径相对它）。

    `epoch`：第几次重复（V2）。>1 时 run_id 加 `#e{n}` 后缀、调用方给独立工作目录——
    同一样本的各 epoch 互不残留（R3 的 eval_set 按 epoch 起子进程）。
    `trace_backend`：与 scorer 的读账后端同源（langfuse 需本机服务在跑）。
    `run_config_path`：task 落盘的预算配置；子进程原路径传给唯一装配点。
    """
    assert Path.cwd().resolve() == REPO_ROOT.resolve(), "run_one 要从仓库根起跑"
    assert epoch >= 1, "epoch 从 1 起"
    _load_env(REPO_ROOT / ".env")
    work.mkdir(parents=True, exist_ok=True)
    run_id = run_id_for(sample.sample_id, epoch)
    if not _has_start(sample, work, run_id):
        return

    with ExitStack() as cleanup:
        build_branch = _branch_builder(
            work, models, run_id, trace_backend, run_config_path, cleanup
        )
        try:
            manifest = prepare_archive(sample, work / "start")
            result = restore_run(manifest, build_branch, sample_id=sample.sample_id)
            (work / RUN_RESULT).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except CheckpointIncompatible as exc:
            _record(work, run_id, invalid=f"存档拒载：{exc}")
            return
        except Exception as exc:  # noqa: BLE001 —— 运行错误保留给红线 R1
            _record(work, run_id, error=f"{type(exc).__name__}: {exc}")
            return
    _record(work, run_id, branch=result.branch)


def _has_start(sample: EvalSample, work: Path, run_id: str) -> bool:
    """起点缺失时写明无效原因；不启动世界或模型。"""
    manifest = (
        DATASET_DIR / sample.dataset_version / "archives" / sample.start.archive / "manifest.json"
    )
    if manifest.is_file():
        return True
    _record(
        work,
        run_id,
        invalid=(
            f"起点存档缺失：{manifest}"
            "（python -m evals.agent_short_goal_run.dataset.build.pack 重打）"
        ),
    )
    return False


def _branch_builder(
    work: Path,
    models: dict[str, str],
    run_id: str,
    trace_backend: str,
    run_config_path: str,
    cleanup: ExitStack,
) -> Callable[[str], RunRuntime]:
    """装配每条恢复执行线，并立即登记世界租约的退出清理。"""

    def build_branch(branch: str) -> RunRuntime:
        roots_kw = {
            "memory_root": work / "memory",
            "checkpoint_root": work / "checkpoints",
        }
        if trace_backend == "local":
            roots_kw["trace_root"] = work / "trace"
        harness, game = build_real(
            run_id=run_id,
            branch=branch,
            trace_backend=trace_backend,
            config=run_config_path,
            **models,
            **roots_kw,
        )
        cleanup.callback(game.release_lease)
        return harness.deps

    return build_branch


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


def _load_env(path: Path) -> None:
    """把 `.env` 的 KEY=VALUE 注入环境；外部已有的同名变量优先。

    值两端成对的引号（`"` / `'`）剥掉——dotenv 惯例允许带引号，而 `LANGFUSE_BASE_URL`
    带着引号会让 httpx 报"缺协议头"（335 首跑实锤）。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ")
        key, sep, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if (
            line
            and not line.startswith("#")
            and sep
            and key.strip().isidentifier()
            and value.strip()
        ):
            os.environ.setdefault(key.strip(), value.strip())


__all__ = ["run_id_for", "run_one"]
