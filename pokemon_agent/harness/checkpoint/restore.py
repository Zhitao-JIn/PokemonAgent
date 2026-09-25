"""`restore_run`：从一份存档恢复出一条新执行线，在图里接着跑到 run 结束（spec v2 §七）。

`restore_run` = `open_branch`（登记、装配、回档、首条账）+ `resume`（进图）。

两级存档都不嵌在任何 `act` 里，所以恢复全程在图里正常跑：
run 级把 `RunState` 原件改上新 `branch`，从 `begin` 之后进图；episode 级把 run 图"进 `act` 前"
那条的值以 `plan_run` 的名义写进新 thread（下一格即 `act`），再 `invoke(None)`——`act` 照常
派这一局、照常存档。

**到某个 task（`to_task`）**：episode 级恢复 + 回放。磁带取自起点存档里 `along` 那条执行线封存的账
（`trace@<along>/`，intent C14），切到目标 task 的 `task_start` 之前；装配函数据此把真件包成磁带件
（`tools/replay`）。回放段里存档器暂停；走到目标 task 开局时切换：读它的开局世界快照、存档器恢复、
指定这一局的起点存档、记 `checkpoint_restore`，此后一切照常。
"""

from __future__ import annotations

import json
import logging
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
from pokemon_agent.schemas.harness.domain import CheckpointMark, EpisodeOutput, TraceEvent
from pokemon_agent.tools.replay import ReplayDiverged, Tape, event_content, event_meta

from ..run import run_entry
from ..run.run_state import RunState
from ..run.runtime import RunRuntime
from .branches import BranchRecord, read_branches, register_branch
from .checkpointer import SEALED_PREFIX, Checkpointer
from .errors import CheckpointIncompatible, CheckpointNotFound
from .manifest import (
    CheckpointManifest,
    LineageLink,
    launch_relative,
    read_manifest,
    state_schema_hash,
)

logger = logging.getLogger(__name__)

BuildBranch = Callable[[str, list[LineageLink], Tape | None], RunRuntime]
"""装配一条执行线：`(分支名, 血缘, 磁带) -> RunRuntime`；有磁带时把真件包成磁带件。
真机包一层 `build_real`。"""

SOURCE = "checkpoint.restore"


@dataclass(frozen=True)
class OpenedBranch:
    """一条刚恢复好、还没开跑的执行线：世界与记忆已回到存档那一刻。"""

    deps: RunRuntime
    manifest: CheckpointManifest
    record: BranchRecord
    pre_run: RunState
    """run 级：进图前的原件；episode 级：run 图进 `act` 前的状态。"""
    tape: Tape | None = None
    """回放到某个 task 时的磁带；首条账要等切换时才记。"""


@dataclass(frozen=True)
class _ReplayPlan:
    """回放的准备：父线、血缘、磁带、目标 task 的开局世界。"""

    parent: str
    lineage: list[LineageLink]
    tape: Tape
    world_path: str
    fork: TraceEvent


def restore_run(
    manifest_path: str | Path,
    build_branch: BuildBranch,
    *,
    to_task: str | None = None,
    along: str | None = None,
) -> tuple[list[EpisodeOutput], int, int, float]:
    """从 `manifest_path` 那份存档恢复出一条新执行线，跑到 run 结束，返回 run 级四元组。

    to_task：回放到这一局的哪个 task 开局再接着跑（只对 episode 级存档）；None = 不回放。
    along：沿哪条执行线的账回放（缺省 = 存档所在的执行线）。
    = `resume(open_branch(...))`。失败见两者。
    """
    return resume(open_branch(manifest_path, build_branch, to_task=to_task, along=along))


def open_branch(
    manifest_path: str | Path,
    build_branch: BuildBranch,
    *,
    to_task: str | None = None,
    along: str | None = None,
) -> OpenedBranch:
    """恢复的前半段：登记新执行线、装配、世界与记忆回档；不回放时记首条账。不开跑。

    失败：清单缺失 / 损坏 → `CheckpointNotFound` / `CheckpointCorrupt`；状态结构不兼容 →
    `CheckpointIncompatible`；回放的账或目标 task 找不到 → `CheckpointNotFound`。都在登记分支前。
    """
    # 步骤 1：读清单，核版本。
    path = Path(manifest_path)
    run_dir = path.parent.parent
    manifest = read_manifest(path)
    if manifest.code.state_schema_hash != state_schema_hash():
        raise CheckpointIncompatible(f"{manifest.checkpoint_id} 的状态结构与当前代码不同，拒绝加载")

    # 步骤 2：定父线与血缘（回放时由磁带定），登记新执行线，按它装配一套 runtime。
    plan = None
    if to_task is None:
        parent = manifest.branch
        link = LineageLink(
            branch=manifest.branch,
            fork_uuid=manifest.last_event_uuid,
            fork_ts=manifest.last_event_ts,
            checkpoint_id=manifest.checkpoint_id,
        )
        lineage = [*manifest.lineage, link]
    else:
        plan = _plan_replay(run_dir, manifest, to_task, along or manifest.branch)
        parent, lineage = plan.parent, plan.lineage
    record = register_branch(run_dir, parent=parent, lineage=lineage)
    deps = build_branch(record.branch, record.lineage, plan.tape if plan else None)
    ck = deps.checkpointer
    assert ck is not None and ck.branch == record.branch, "装配出的存档器不是这条新执行线的"
    if ck.code.git_commit != manifest.code.git_commit:
        logger.warning(
            "存档 %s 的代码版本 %s 与当前 %s 不同",
            manifest.checkpoint_id,
            manifest.code.git_commit,
            ck.code.git_commit,
        )

    # 步骤 3：世界与记忆回到存档那一刻；不回放时记首条账，回放时挂好切换要做的事。
    pre_run = _pre_run_state(ck, manifest)
    ck.memory.restore_memory(
        FromHarnessToMemoryToolRestoreMemoryReq(archive=manifest.memory_archive)
    )
    ck.game.reset(FromHarnessToGameToolResetReq(task=pre_run.goals[0].task))
    ck.game.load_state(
        FromHarnessToGameToolLoadStateReq(path=str(path.parent / manifest.world_file))
    )
    if plan is None:
        _note_restore(
            ck,
            _restore_mark(manifest, path, parent, manifest.last_event_uuid, ""),
            {"episode_id": manifest.run_id, "task_id": manifest.run_id, "step": pre_run.step},
        )
    else:
        ck.paused = True
        mark = _restore_mark(manifest, path, parent, plan.fork.uuid, to_task or "")
        plan.tape.on_switch.append(_switch(ck, manifest, mark, plan.world_path))
    return OpenedBranch(deps, manifest, record, pre_run, plan.tape if plan else None)


def resume(opened: OpenedBranch) -> tuple[list[EpisodeOutput], int, int, float]:
    """恢复的后半段：在新 thread 上进 run 图跑到底。

    失败：回放走偏或没走到目标 task → `ReplayDiverged`（不记 `run_error`：新执行线还没开账）；
    其余 run 级异常记 `run_error` 后原样上抛。
    """
    deps, manifest, record = opened.deps, opened.manifest, opened.record
    ck = deps.checkpointer
    assert ck is not None
    thread = run_entry.thread_id(manifest.run_id, record.branch)
    state = opened.pre_run.model_copy(update={"branch": record.branch})
    try:
        if manifest.level == "run":
            final = run_entry.invoke_run(deps, ck.run_graph, state, thread=thread)
        else:
            config = ck.run_graph.update_state(
                {"configurable": {"thread_id": thread}}, _fields(state), as_node="plan_run"
            )
            assert ck.run_graph.get_state(config).next == ("act",), "写入后 run 图下一格不是 act"
            final = run_entry.invoke_run(deps, ck.run_graph, None, thread=thread)
    except ReplayDiverged:
        raise
    except Exception as exc:
        if opened.tape is not None and opened.tape.diverged is not None:
            raise opened.tape.diverged from exc
        if opened.tape is not None and not opened.tape.switched:
            raise ReplayDiverged(f"回放段里出了异常：{type(exc).__name__}: {exc}") from exc
        run_entry.record_run_error(deps, manifest.run_id, exc, source=SOURCE)
        raise
    if opened.tape is not None and not opened.tape.switched:
        raise ReplayDiverged(f"run 跑完了也没走到目标 task {opened.tape.target_task}")
    return run_entry.close(final)


def _plan_replay(
    run_dir: Path, manifest: CheckpointManifest, to_task: str, along: str
) -> _ReplayPlan:
    """读起点存档里 `along` 封存的账，切出磁带，定父线、血缘与目标 task 的开局世界。"""
    assert manifest.level == "episode" and manifest.episode_id, "只能从 episode 级存档回放"
    sealed = run_dir / manifest.checkpoint_id / f"{SEALED_PREFIX}{along}"
    if not sealed.is_dir():
        raise CheckpointNotFound(f"{manifest.checkpoint_id} 里没有执行线 {along} 封存的账")
    events = sorted(
        (
            TraceEvent.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sealed.glob("*.json")
        ),
        key=lambda e: (e.ts, e.uuid),
    )
    at = next(
        (
            i
            for i, e in enumerate(events)
            if e.kind == "task_start"
            and event_meta(e).get("episode_id") == manifest.episode_id
            and event_meta(e).get("task_id") == to_task
        ),
        None,
    )
    if at is None or at == 0:
        raise CheckpointNotFound(f"{along} 在 {manifest.episode_id} 里没有 task {to_task}")
    world = next(
        (
            e
            for e in events[at:]
            if e.kind == "world_snapshot" and event_meta(e).get("task_id") == to_task
        ),
        None,
    )
    if world is None:
        raise CheckpointNotFound(f"{along} 的 task {to_task} 没有开局世界快照")

    # 分叉点是目标 task_start 的前一条；它属于哪条线，新线就从哪条线分出来。
    fork = events[at - 1]
    fork_branch = str(json.loads(fork.meta)["branch"])
    along_lineage = [] if along == "main" else list(read_branches(run_dir)[along].lineage)
    chain = [link.branch for link in along_lineage] + [along]
    cut = chain.index(fork_branch)
    link = LineageLink(
        branch=fork_branch,
        fork_uuid=fork.uuid,
        fork_ts=fork.ts,
        checkpoint_id=manifest.checkpoint_id,
    )
    tape = Tape(events[:at], target_episode=manifest.episode_id, target_task=to_task)
    return _ReplayPlan(
        fork_branch, [*along_lineage[:cut], link], tape, str(event_content(world)["path"]), fork
    )


def _switch(
    ck: Checkpointer, manifest: CheckpointManifest, mark: CheckpointMark, world_path: str
) -> Callable[[dict[str, Any]], None]:
    """切换那一刻要做的事：读目标 task 的开局世界、存档器恢复、指定这一局的起点、记首条账。"""

    def hook(task_meta: dict[str, Any]) -> None:
        ck.game.load_state(FromHarnessToGameToolLoadStateReq(path=world_path))
        ck.paused = False
        ck.open_episode(manifest)
        _note_restore(ck, mark, task_meta)

    return hook


def _pre_run_state(ck: Checkpointer, manifest: CheckpointManifest) -> RunState:
    """run 级：清单里的原件；episode 级：saver 里 run 图进 `act` 前那一条。"""
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


def _fields(state: RunState) -> dict[str, object]:
    """RunState 的全部字段（按通道名），供 `update_state` 整份写入。"""
    return {name: getattr(state, name) for name in RunState.model_fields}


def _restore_mark(
    manifest: CheckpointManifest, path: Path, parent: str, fork_uuid: str, to_task: str
) -> CheckpointMark:
    return CheckpointMark(
        checkpoint_id=manifest.checkpoint_id,
        level=manifest.level,
        manifest_path=launch_relative(path),
        parent_branch=parent,
        parent_last_event_uuid=fork_uuid,
        to_task=to_task,
    )


def _note_restore(ck: Checkpointer, mark: CheckpointMark, where: dict[str, Any]) -> None:
    """新执行线的第一条账 `checkpoint_restore`；签名取恢复落在的位置（run 层或目标 task 开局）。"""
    ck.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECKPOINT_RESTORE,
            meta={
                "source": SOURCE,
                "episode_id": where["episode_id"],
                "task_id": where["task_id"],
                "step": where["step"],
            },
            checkpoint=mark,
        )
    )


__all__ = ["SOURCE", "BuildBranch", "OpenedBranch", "open_branch", "restore_run", "resume"]
