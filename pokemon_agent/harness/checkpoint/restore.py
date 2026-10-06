"""`restore_run`：从一份存档恢复出一条新执行线，在图里接着跑到 run 结束（checkpoint spec §五）。

`restore_run` = `open_branch`（读清单、起新线名、装配、回档、首条账）+ `resume`（进图）。

恢复全程在图里跑：run 级把 `RunState` 原件改上新 `branch`，从 `begin` 之后进图；episode / task 级
把 run 图"进 `act` 前"那条的值以 `plan_run` 的名义写进新 thread（下一格即 `act`），
再 `invoke(None)`。
episode 级下 run 的 `act` 照常派这一局、照常存档；task 级另把 episode 图"进 `act` 前"那条的值放进
存档器的恢复计划，run 的 `act` 取到后经 `episode_entry.resume_episode` 从那里接着跑，
episode 的 `act` 与 `begin_task` 照常执行（新线在目标 task 开局存下自己的 task 级档）。

父线保存在清单的 `branch` 字段；恢复本身依赖清单、LangGraph saver、世界存档与记忆快照。
trace 血缘只用于读取时拼接可见历史，不参与恢复。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolResetReq,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import CheckpointMark, RunResult

from ..episode.episode_state import EpisodeRunState
from ..run import run_entry
from ..run.run_state import RunState
from ..run.runtime import RunRuntime
from .checkpointer import Checkpointer
from .errors import CheckpointIncompatible, CheckpointNotFound
from .manifest import (
    CheckpointManifest,
    launch_relative,
    read_manifest,
    state_schema_hash,
)

logger = logging.getLogger(__name__)

BuildBranch = Callable[[str], RunRuntime]
"""装配一条执行线：`分支名 -> RunRuntime`。真机包一层 `build_real`。"""

SOURCE = "checkpoint.restore"


@dataclass(frozen=True)
class OpenedBranch:
    """一条刚恢复好、还没开跑的执行线：世界与记忆已回到存档那一刻。"""

    deps: RunRuntime
    manifest: CheckpointManifest
    branch: str
    pre_run: RunState
    """run 级：进图前的原件；episode / task 级：run 图进 `act` 前的状态。"""


def restore_run(
    manifest_path: str | Path,
    build_branch: BuildBranch,
    *,
    sample_id: str = "",
) -> RunResult:
    """从 `manifest_path` 那份存档恢复出一条新执行线，跑到 run 结束，返回 `RunResult`。

    = `resume(open_branch(...))`。失败见两者。`sample_id` 原样带回（eval 侧样本标识）。
    """
    return resume(open_branch(manifest_path, build_branch), sample_id=sample_id)


def open_branch(manifest_path: str | Path, build_branch: BuildBranch) -> OpenedBranch:
    """恢复的前半段：读清单、起新线名、装配、回档世界与记忆、记首条账。不开跑。

    失败：清单缺失 / 损坏 → `CheckpointNotFound` / `CheckpointCorrupt`；状态结构不兼容 →
    `CheckpointIncompatible`；saver 缺少所需图状态 → `CheckpointNotFound`。
    """
    # 步骤 1：读清单，核版本。
    path = Path(manifest_path)
    manifest = read_manifest(path)
    if manifest.code.state_schema_hash != state_schema_hash():
        raise CheckpointIncompatible(f"{manifest.checkpoint_id} 的状态结构与当前代码不同，拒绝加载")

    # 步骤 2：起新线名（随机，不读账），按它装配一套 runtime。
    branch = f"b-{uuid.uuid4().hex[:6]}"
    deps = build_branch(branch)
    ck = deps.checkpointer
    assert ck is not None and ck.branch == branch, "装配出的存档器不是这条新执行线的"
    if ck.code.git_commit != manifest.code.git_commit:
        logger.warning(
            "存档 %s 的代码版本 %s 与当前 %s 不同",
            manifest.checkpoint_id,
            manifest.code.git_commit,
            ck.code.git_commit,
        )

    # 步骤 3：读回图状态；task 级把 episode 图的那份放进恢复计划。
    pre_run = _pre_run_state(ck, manifest)
    if manifest.level == "task":
        assert manifest.episode_id is not None and manifest.task_id is not None
        ck.arm_resume(manifest.episode_id, manifest.task_id, _episode_state(ck, manifest))

    # 步骤 4：世界与记忆回到存档那一刻，记首条账。
    ck.memory.restore_memory(
        FromHarnessToMemoryToolRestoreMemoryReq(archive=manifest.memory_archive)
    )
    ck.game.reset(FromHarnessToGameToolResetReq(task=pre_run.goals[0].task))
    ck.game.load_state(
        FromHarnessToGameToolLoadStateReq(path=str(path.parent / manifest.world_file))
    )
    _note_restore(
        ck,
        CheckpointMark(level=manifest.level, manifest_path=launch_relative(path)),
        {
            # 位约定与存档侧对齐（checkpointer.save：task 级放真 episode/task 号，
            # 其余两级两位都放 run_id）——恢复账属于恢复落点那一层。
            "episode_id": manifest.episode_id if manifest.level == "task" else manifest.run_id,
            "task_id": manifest.task_id if manifest.level == "task" else manifest.run_id,
            "step": pre_run.step,
            "checkpoint_id": manifest.checkpoint_id,
        },
    )
    return OpenedBranch(deps, manifest, branch, pre_run)


def resume(opened: OpenedBranch, *, sample_id: str = "") -> RunResult:
    """恢复的后半段：在新 thread 上进 run 图跑到底。

    失败：run 级异常记 `run_error` 后原样上抛。`sample_id` 原样带回 `RunResult`。
    """
    deps, manifest, branch = opened.deps, opened.manifest, opened.branch
    ck = deps.checkpointer
    assert ck is not None
    thread = run_entry.thread_id(manifest.run_id, branch)
    state = opened.pre_run.model_copy(update={"branch": branch})
    try:
        if manifest.level == "run":
            final = run_entry.invoke_run(deps, ck.run_graph, state, thread=thread)
        else:
            config = ck.run_graph.update_state(
                {"configurable": {"thread_id": thread}}, _fields(state), as_node="plan_run"
            )
            assert ck.run_graph.get_state(config).next == ("act",), "写入后 run 图下一格不是 act"
            final = run_entry.invoke_run(deps, ck.run_graph, None, thread=thread)
    except Exception as exc:
        run_entry.record_run_error(deps, manifest.run_id, exc, source=SOURCE)
        raise
    return run_entry.close(final, deps, manifest.run_id, sample_id=sample_id)


def _pre_run_state(ck: Checkpointer, manifest: CheckpointManifest) -> RunState:
    """run 级：清单里的原件；episode / task 级：saver 里 run 图进 `act` 前那一条。"""
    if manifest.level == "run":
        assert manifest.run_state is not None
        return manifest.run_state
    ref = manifest.run_ref
    assert ref is not None
    snapshot = ck.run_graph.get_state(
        {"configurable": {"thread_id": ref.thread_id, "checkpoint_id": ref.checkpoint_id}}
    )
    assert snapshot.next == ("act",), f"{manifest.checkpoint_id} 的 run 定位不是进 act 前"
    return RunState.model_validate(snapshot.values)


def _episode_state(ck: Checkpointer, manifest: CheckpointManifest) -> EpisodeRunState:
    """task 级：saver 里 episode 图进 `act` 前那一条的值（直接问 saver——图外按嵌套命名空间
    `get_state` 会被转派给子图）。从没写过的 channel 不落盘，取模型缺省值。

    失败：saver 里没有这一条 → `CheckpointNotFound`。
    """
    ref = manifest.episode_ref
    assert ref is not None and ck.run_graph.checkpointer is not None
    saved = ck.run_graph.checkpointer.get_tuple({"configurable": ref.model_dump()})
    if saved is None:
        raise CheckpointNotFound(f"{manifest.checkpoint_id} 的 episode 定位在 saver 里找不到")
    values = saved.checkpoint["channel_values"]
    return EpisodeRunState.model_validate(
        {name: values[name] for name in EpisodeRunState.model_fields if name in values}
    )


def _fields(state: RunState) -> dict[str, object]:
    """RunState 的全部字段（按通道名），供 `update_state` 整份写入。"""
    return {name: getattr(state, name) for name in RunState.model_fields}


def _note_restore(ck: Checkpointer, mark: CheckpointMark, where: dict[str, Any]) -> None:
    """新执行线的第一条账 `checkpoint_restore`；meta 带恢复落在的位置与存档 id。"""
    ck.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECKPOINT_RESTORE,
            meta={"source": SOURCE, **where},
            checkpoint=mark,
        )
    )


__all__ = ["SOURCE", "BuildBranch", "OpenedBranch", "open_branch", "restore_run", "resume"]
