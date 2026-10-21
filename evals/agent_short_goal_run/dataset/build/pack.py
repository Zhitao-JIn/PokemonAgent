"""起点打包工具（**数据准备，用户本机跑**）：原始 `.state` → run 级存档。

用法（从仓库根）：

    python -m evals.agent_short_goal_run.dataset.build.pack  # 打当前默认版本全部样本
    python -m evals.agent_short_goal_run.dataset.build.pack --samples id1,id2   # 只打指定样本
    python -m evals.agent_short_goal_run.dataset.build.pack --version v1

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

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.solver.runner.one import run_id_for
from evals.common.memory_server import clear_memory
from evals.common.overlay import eval_overlay, sample_overlay, write_overlay
from evals.paths import REPO_ROOT
from evals.runconfig import load_config
from pokemon_agent.brain import Task
from pokemon_agent.build import build_real
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.direct.trace.content import CheckpointSaveContent
from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcpclient import McpTransportError
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.schemas.harness import TraceKind

from ..loader import DATASET_DIR, load_samples, sha256_of


def pack_one(sample: EvalSample, version: str, archive_root: Path | None = None) -> Path:
    """打一条样本的起点存档，返回存档目录（`archives/<样本>/`）。

    前置条件：`sample.start.kind == "archive"` 且来源 `.state` 存在、哈希与
    `source_sha256` 一致；评测专用 memory server（带 --enable-admin）已起。
    失败：哈希不符 / 起点缺失 / reset 被拒绝 / 未落 checkpoint_save → 异常上抛。
    装配成功后，无论打包成功或异常退出都归还本客户端租约。
    """
    state = DATASET_DIR / version / sample.start.source_state
    if not state.is_file() or sha256_of(state) != sample.start.source_sha256:
        raise ValueError(f"来源 .state 缺失或哈希对不上：{sample.start.source_state}")

    _clear_memory()
    run_id = run_id_for(sample.sample_id)
    tmp = Path(tempfile.mkdtemp(prefix=f"pack-{sample.sample_id}-"))
    game: WorldMcpTool | None = None
    try:
        roots = {
            "trace_root": tmp / "trace",
            "memory_root": tmp / "memory",
            "checkpoint_root": tmp / "checkpoints",
        }
        eval_config, _digest = write_overlay(
            tmp / "config-pack.json",
            {
                **eval_overlay({**load_config(), "trace_backend": "local"}),
                **sample_overlay(run_id=run_id, branch="main", work=tmp),
            },
        )
        harness, game = build_real(config=eval_config)
        game.use_start_state(state)
        task = Task(
            task_id=sample.sample_id,
            goal=sample.goal,
            success_criteria=sample.success_criteria,
            max_steps=sample.max_steps,
            initial_state_hint=sample.initial_state_hint,
        )
        harness.run(run_id, [task], checkpoint_only=True)
        return _copy_checkpoint(run_id, roots, sample.sample_id, version, archive_root)
    finally:
        try:
            if game is not None:
                _release_world(game)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _clear_memory() -> None:
    """清空评测专用记忆；缺地址或服务端失败直接上抛。"""
    load_env_file()
    memory_url = env_str("MCP_MEMORY_SERVER_URL")
    if not memory_url:
        raise McpTransportError(
            "memory 只经 MCP：设 MCP_MEMORY_SERVER_URL 或传 memory_server_url，并先起 memory server"
        )
    clear_memory(MemoryTool.build(memory_server_url=memory_url))


def _release_world(game: WorldMcpTool) -> None:
    """归还租约；若打包与释放均失败，保留两份异常，避免掩盖打包失败原因。"""
    active_error = sys.exception()
    try:
        game.release_lease()
    except Exception as cleanup_error:
        if active_error is None:
            raise
        raise BaseExceptionGroup(
            f"打包失败（{active_error}），且 world 租约释放失败（{cleanup_error}）",
            [active_error, cleanup_error],
        ) from None


def _copy_checkpoint(
    run_id: str,
    roots: dict[str, Path],
    sample_id: str,
    version: str,
    archive_root: Path | None = None,
) -> Path:
    """拷贝已成功保存的 checkpoint 与记忆快照，改写 manifest 的相对路径。"""
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

    dst = (archive_root or (DATASET_DIR / version / "archives")) / sample_id
    if archive_root is not None and dst.exists():
        raise FileExistsError(dst)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    snapshots = roots["memory_root"] / "snapshots"
    if snapshots.is_dir():
        shutil.copytree(snapshots, dst / "memory" / "snapshots", dirs_exist_ok=True)
    manifest_file = dst / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    memory_path = dst / "memory" / "snapshots" / Path(manifest["memory_archive"]).name
    manifest["memory_archive"] = (
        str(memory_path.resolve())
        if archive_root
        else memory_path.relative_to(DATASET_DIR / version).as_posix()
    )
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def main(argv: list[str] | None = None) -> int:
    """命令行入口（数据准备工具，非 eval 跑批入口）。

    前置条件：先起 world server（任意 --state-file 或无）与 --enable-admin 的
    memory server；本命令会清空该 memory server。
    """
    parser = argparse.ArgumentParser(prog="python -m evals.agent_short_goal_run.dataset.build.pack")
    parser.add_argument("--version", default="v2")
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--samples", default="", help="逗号分隔的样本 id；缺省打全部")
    args = parser.parse_args(argv)

    load_env_file(REPO_ROOT / ".env")
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
            dst = pack_one(sample, args.version, args.archive_root)
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
