"""跑一条样本（在独立子进程里，工作目录 = 仓库根）：打包起点 → 从存档恢复 → 跑完一个 run。

只落盘、不判定。工作目录 `runs/<sample_id>/` 下放本条样本独立的
`trace/`、`memory/`、`checkpoints/`，最后写 `run.json`（`run_id`、`invalid`、`error`）。
起点问题（文件缺、哈希不对、存档拒载）记 `invalid`，
run 自己出错只记 `error`——它是被测系统的问题，由红线 R1 判。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from evals.e2e.dataset import REPO_ROOT, sha256_of
from evals.e2e.report import RUN_RECORD
from evals.e2e.schemas import EvalSample
from pokemon_agent.brain import Task
from pokemon_agent.build import build_real
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.checkpoint import CheckpointIncompatible, restore_run
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace import TraceTool, parse
from pokemon_agent.tools.trace.content import CheckpointSaveContent

ROM = "assets/rom"
"""ROM 路径，相对仓库根（`assets/` 不进 git）。"""

KNOWLEDGE_DIR = REPO_ROOT / "memory" / "knowledge_memory"
"""知识库源目录；开知识时整个拷进样本的记忆根。"""


def run_one(
    sample: EvalSample, work: Path, models: dict[str, str], *, knowledge: bool, speed: int
) -> None:
    """跑一条样本并写 `run.json`。前置条件：当前工作目录是仓库根（存档清单里的路径相对它）。"""
    assert Path.cwd().resolve() == REPO_ROOT.resolve(), "run_one 要从仓库根起跑"
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

    # 步骤 1：起点——打包 run 级存档（run_begin），或拷来真实 run 的 episode 级存档。
    run_id = f"eval-{sample.sample_id}"
    try:
        if sample.start.kind == "run_begin":
            manifest = _pack(sample, run_id, roots, models, speed)
        else:
            manifest, run_id = _adopt(sample, roots)
    except (OSError, ValueError, AssertionError) as exc:
        _record(work, run_id, invalid=f"起点不可用：{type(exc).__name__}: {exc}")
        return

    # 步骤 2：从存档恢复出新执行线，跑到 run 结束。
    def build_branch(branch: str) -> RunRuntime:
        harness, _game = build_real(
            ROM,
            None,
            run_id=run_id,
            branch=branch,
            speed=speed,
            **models,
            **roots,
        )
        return harness.deps

    try:
        restore_run(manifest, build_branch)
    except CheckpointIncompatible as exc:
        _record(work, run_id, invalid=f"存档拒载：{exc}")
        return
    except Exception as exc:  # noqa: BLE001 —— run 自己出错照样收尾，交给红线 R1
        _record(work, run_id, error=f"{type(exc).__name__}: {exc}")
        return
    _record(work, run_id)


def _pack(
    sample: EvalSample, run_id: str, roots: dict[str, Path], models: dict[str, str], speed: int
) -> Path:
    """钉死 `.state` + 目标 → run 级存档，返回清单路径。

    失败：起点文件缺或哈希不对 → `ValueError`。
    """
    state = REPO_ROOT / sample.start.state_path
    if not state.is_file() or sha256_of(state) != sample.start.state_sha256:
        raise ValueError(f"起点文件缺失或哈希不对：{sample.start.state_path}")
    harness, _game = build_real(ROM, str(state), run_id=run_id, speed=speed, **models, **roots)
    task = Task(
        task_id=sample.sample_id,
        goal=sample.goal,
        success_criteria=sample.success_criteria,
        max_steps=sample.max_steps,
        initial_state_hint=sample.initial_state_hint,
    )
    harness.run(run_id, [task], checkpoint_only=True)
    trace = TraceTool.build(run_id=run_id, trace_root=roots["trace_root"])
    saves = [
        parse(e)
        for e in trace.read_events({"run_id": run_id})
        if e.kind == TraceKind.CHECKPOINT_SAVE
    ]
    assert saves, "打包没有落下 checkpoint_save"
    content = saves[-1].content
    assert isinstance(content, CheckpointSaveContent)
    return Path(content.manifest_path)


def _adopt(sample: EvalSample, roots: dict[str, Path]) -> tuple[Path, str]:
    """拷来真实 run 的存档根与记忆根，返回（清单路径，原 run_id）。"""
    src_ckpt = REPO_ROOT / sample.start.checkpoint_root
    shutil.copytree(src_ckpt, roots["checkpoint_root"], dirs_exist_ok=True)
    if sample.start.memory_root:
        shutil.copytree(
            REPO_ROOT / sample.start.memory_root, roots["memory_root"], dirs_exist_ok=True
        )
    manifest = roots["checkpoint_root"] / sample.start.manifest_path
    run_id = json.loads(manifest.read_text(encoding="utf-8"))["run_id"]
    return manifest, run_id


def _record(work: Path, run_id: str, *, invalid: str = "", error: str = "") -> None:
    """写本条样本的批跑小结。"""
    payload = {"run_id": run_id, "invalid": invalid, "error": error}
    (work / RUN_RECORD).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_env(path: Path) -> None:
    """把 `.env` 的 KEY=VALUE 注入环境；外部已有的同名变量优先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ")
        key, sep, value = line.partition("=")
        if (
            line
            and not line.startswith("#")
            and sep
            and key.strip().isidentifier()
            and value.strip()
        ):
            os.environ.setdefault(key.strip(), value.strip())


__all__ = ["ROM", "run_one"]
