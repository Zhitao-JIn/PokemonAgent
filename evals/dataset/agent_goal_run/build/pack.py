"""起点打包工具（**数据准备，用户本机跑**）：原始 `.state` → run 级存档。

用法（从仓库根）：

    python -m evals.dataset.agent_goal_run.build.pack                     # 打 v1 全部样本
    python -m evals.dataset.agent_goal_run.build.pack --samples id1,id2   # 只打指定样本
    python -m evals.dataset.agent_goal_run.build.pack --version v1

逐条：核来源 `.state` 哈希（数据集里的 `source_sha256`）→ `build_real` 起 PyBoy 载入
场景 → `harness.run(checkpoint_only=True)`（真 `Checkpointer.save` 产出 manifest，
`state_schema_hash` 盖当前的）→ 把存档整目录拷进 `data/<version>/archives/<样本>/`。

串行起模拟器（一次一个，Event 41 红线）；需要 pyboy（.venv 已装）。
manifest 跟代码走：动了 `RunState` 结构 → 旧存档被 restore_run 拒载 → 重跑本工具即可
（用户已接受重打，0929 定向）。重打会覆盖同名产物。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from evals.dataset.agent_goal_run.schemas import EvalSample
from evals.paths import REPO_ROOT
from evals.solvers.agent_goal_run.runner.one import ROM, _load_env, run_id_for
from pokemon_agent.brain import Task
from pokemon_agent.build import build_real
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.direct.trace.content import CheckpointSaveContent
from pokemon_agent.schemas.harness import TraceKind

from ..loader import DATASET_DIR, load_samples, sha256_of


def pack_one(sample: EvalSample, version: str) -> Path:
    """打一条样本的起点存档，返回存档目录（`archives/<样本>/`）。

    前置条件：`sample.start.kind == "archive"` 且来源 `.state` 存在、哈希与
    `source_sha256` 一致。失败：哈希不符 / 起点缺失 / 打包没落 checkpoint_save → 异常上抛。
    """
    state = DATASET_DIR / version / sample.start.source_state
    if not state.is_file() or sha256_of(state) != sample.start.source_sha256:
        raise ValueError(f"来源 .state 缺失或哈希对不上：{sample.start.source_state}")

    # run_id 用正式名（eval-<样本>）：manifest 的 RunState.run_id 会被 restore 原样带进
    # 跑批账本，必须与 scorer 读的 run_id 一致（pack 走 local 后端，无 Langfuse 撞车）。
    run_id = run_id_for(sample.sample_id)
    tmp = Path(tempfile.mkdtemp(prefix=f"pack-{sample.sample_id}-"))
    try:
        roots = {
            "trace_root": tmp / "trace",
            "memory_root": tmp / "memory",
            "checkpoint_root": tmp / "checkpoints",
        }
        harness, _game = build_real(
            ROM, str(state), run_id=run_id, speed=0, trace_backend="local", **_models(), **roots
        )
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
        src = Path(content.manifest_path).parent

        dst = DATASET_DIR / version / "archives" / sample.sample_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        # 记忆快照在 memory_root（checkpoint 目录之外），一并拷进存档；
        # manifest 里的绝对路径改写成仓库相对路径（run_one 保证 cwd=仓库根）。
        snapshots = roots["memory_root"] / "snapshots"
        if snapshots.is_dir():
            shutil.copytree(snapshots, dst / "memory" / "snapshots", dirs_exist_ok=True)
        manifest_file = dst / "manifest.json"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest["memory_archive"] = str(
            (dst / "memory" / "snapshots" / Path(manifest["memory_archive"]).name).relative_to(
                DATASET_DIR / version
            )
        )
        manifest_file.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return dst
    finally:
        # 尽力清理：sqlite 存档器的连接可能没关（WinError 32），残留 temp 目录无害。
        shutil.rmtree(tmp, ignore_errors=True)


def _models() -> dict[str, str]:
    """链路型号从 `evals/config.json` 取（打包不调模型，只是 build_real 的形参）。"""
    from evals.runconfig import load_config, resolve_models

    return resolve_models(load_config()["models"])


def main(argv: list[str] | None = None) -> int:
    """命令行入口（数据准备工具，非 eval 跑批入口）。"""
    parser = argparse.ArgumentParser(prog="python -m evals.dataset.agent_goal_run.build.pack")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--samples", default="", help="逗号分隔的样本 id；缺省打全部")
    args = parser.parse_args(argv)

    _load_env(REPO_ROOT / ".env")
    from evals.runconfig import load_config

    cfg_version = str(load_config().get("version", args.version))
    assert cfg_version == args.version, f"config.json 的 version={cfg_version} 与 --version 不一致"
    samples = load_samples(args.version)
    wanted = {s for s in args.samples.split(",") if s}
    targets = [s for s in samples if not wanted or s.sample_id in wanted]

    failed: list[str] = []
    for sample in targets:
        assert sample.start.kind == "archive" and sample.start.source_state, (
            f"{sample.sample_id}：起点不是 archive 形态（缺 source_state）"
        )
        try:
            dst = pack_one(sample, args.version)
            print(f"✓ {sample.sample_id} → {dst}", flush=True)
        except Exception as exc:  # noqa: BLE001 —— 逐条打包，失败继续下一条，最后汇总
            failed.append(sample.sample_id)
            print(f"✗ {sample.sample_id}：{type(exc).__name__}: {exc}", flush=True)
    if failed:
        print(f"失败 {len(failed)} 条：{failed}", file=sys.stderr)
        return 1
    print(f"全部 {len(targets)} 条打包完成 → {DATASET_DIR / args.version / 'archives'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
