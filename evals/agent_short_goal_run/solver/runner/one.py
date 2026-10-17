"""跑一条样本（在独立子进程里，工作目录 = 仓库根）：直读打包好的起点存档 → 恢复 → 跑完一个 run。

只落盘、不判定。工作目录 `runs/<sample_id>[#e<n>]/` 下放本条样本独立的
`trace/`、`memory/`、`checkpoints/`，最后写 `run.json`（`run_id`、`invalid`、`error`）
与 `run_result.json`（`RunResult`，V8）。
起点存档缺失或被拒载记 `invalid`（先跑
`python -m evals.agent_short_goal_run.dataset.build.pack` 重打），
run 自己出错只记 `error`——它是被测系统的问题，由红线 R1 判。
"""

from __future__ import annotations

import json
import os
import shutil
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

ROM = "assets/rom"
"""ROM 路径，相对仓库根（`assets/` 不进 git）。"""

KNOWLEDGE_DIR = REPO_ROOT / "memory" / "knowledge_memory"
"""知识库源目录；开知识时整个拷进样本的记忆根。"""


def run_one(
    sample: EvalSample,
    work: Path,
    models: dict[str, str],
    *,
    run_config_path: str,
    knowledge: bool,
    speed: int,
    epoch: int = 1,
    trace_backend: str = "local",
    watch: bool = False,
) -> None:
    """跑一条样本并写 `run.json`。前置条件：当前工作目录是仓库根（存档清单里的路径相对它）。

    `epoch`：第几次重复（V2）。>1 时 run_id 加 `#e{n}` 后缀、调用方给独立工作目录——
    同一样本的各 epoch 互不残留（R3 的 eval_set 按 epoch 起子进程）。
    `trace_backend`：与 scorer 的读账后端同源（langfuse 需本机服务在跑）。
    `run_config_path`：task 落盘的预算配置；子进程原路径传给唯一装配点。
    `watch`：开 SDL 窗口人看模拟器（默认无头批量）。
    """
    assert Path.cwd().resolve() == REPO_ROOT.resolve(), "run_one 要从仓库根起跑"
    assert epoch >= 1, "epoch 从 1 起"
    _load_env(REPO_ROOT / ".env")
    work.mkdir(parents=True, exist_ok=True)
    roots = {
        "trace_root": work / "trace",
        "memory_root": work / "memory",
        "checkpoint_root": work / "checkpoints",
    }
    if knowledge and KNOWLEDGE_DIR.is_dir():
        shutil.copytree(
            KNOWLEDGE_DIR, roots["memory_root"] / "knowledge_memory", dirs_exist_ok=True
        )

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
        # trace_backend 与 scorer 的读账后端同源（config.json 的 trace_backend）；
        # watch 开 SDL 窗口（config.json 的 watch）。
        # trace_root 只对 local 后端有意义——langfuse 传了会被 TraceTool.build 拒收。
        roots_kw = {
            "memory_root": roots["memory_root"],
            "checkpoint_root": roots["checkpoint_root"],
        }
        if trace_backend == "local":
            roots_kw["trace_root"] = roots["trace_root"]
        harness, _game = build_real(
            run_id=run_id,
            branch=branch,
            trace_backend=trace_backend,
            config=run_config_path,
            **models,
            **roots_kw,
        )
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


__all__ = ["ROM", "run_id_for", "run_one"]
