"""`Checkpointer`：三级存档（`docs/checkpoint/spec.md` §一、§四）。

存档点由调用方显式调用 `save()`，三级都在各自那一层的 begin、先于本层开局账：
- run 级：`run_entry.new_run`（reset 之后、进图之前），存 `RunState` 原件；
- episode 级：run 的 `act`（`dispatch` 之后、跑这一局之前），记 run 图"进 `act` 前"那条的位置；
- task 级：`begin_task` 第一件事，另记 episode 图"进 `act`、派这个 task 前"那条的位置。

两个位置都从执行上下文的 `checkpoint_map` 取：`""` 是 run 图（根图），当前命名空间去掉最后一段
是 episode 图（它在 run 的 `act` 里被 invoke）。每一级都存世界与记忆整根。存档不读 trace。

恢复到某个 task 时，"这一局要从哪份状态接着跑"也寄存在这里（`arm_resume` / `take_resume`）：
恢复路径放进去，run 的 `act` 取一次就清空——它不进图状态。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from langgraph.config import get_config
from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.direct.interface import GameToolPort, MemoryToolPort, TraceToolPort
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import CheckpointMark

from ..episode.episode_state import EpisodeRunState
from ..run.run_state import RunState
from .manifest import (
    WORLD_FILENAME,
    CheckpointManifest,
    GraphRef,
    Level,
    code_stamp,
    launch_relative,
    write_manifest,
)

SOURCE = "checkpoint.save"
NS_SEP = "|"
"""LangGraph 嵌套命名空间的分隔符：`act:<id1>` 再往里一层是 `act:<id1>|act:<id2>`。"""


class Checkpointer:
    """存档器。一次装配一份，三层 runtime 持有同一个实例。"""

    def __init__(
        self,
        *,
        root: Path,
        run_graph: CompiledStateGraph,
        game: GameToolPort,
        memory: MemoryToolPort,
        trace: TraceToolPort,
        branch: str = "main",
        models: dict[str, str] | None = None,
    ) -> None:
        """root：存档根（`<root>/<run_id>/<checkpoint_id>/`）。

        run_graph：挂着 saver 的 run 图（定位的核对、恢复时读值都经它与它的 saver）。
        branch：本执行线的分支名。
        """
        assert branch, "Checkpointer needs a non-empty branch"
        assert run_graph.checkpointer is not None, "run 图必须挂 saver 才能存档"
        self.root = Path(root)
        self.run_graph = run_graph
        self.game = game
        self.memory = memory
        self.trace = trace
        self.branch = branch
        self.models = dict(models or {})
        self.code = code_stamp()
        self._resume: tuple[str, str, EpisodeRunState] | None = None
        """恢复计划：`(episode_id, task_id, episode 图进 act 前的状态)`；run 的 act 取一次即清。"""
        self._expect_task: str | None = None
        """恢复后第一次 task 级存档应是哪个 task（`dispatch_task` 重算出的就该是目标 task）。"""

    def arm_resume(self, episode_id: str, task_id: str, state: EpisodeRunState) -> None:
        """放进恢复计划：这一局不从头开，从 `state`（episode 图进 `act` 前）接着跑到 `task_id`。

        前置条件：还没有待取的计划。
        """
        assert self._resume is None, "上一份恢复计划还没被取走"
        assert state.episode_id == episode_id, "恢复计划的状态不是这一局的"
        self._resume = (episode_id, task_id, state)

    def take_resume(self, episode_id: str) -> EpisodeRunState | None:
        """取走恢复计划（run 的 `act` 调）；没有计划返回 None。

        前置条件：有计划时，run 的 `act` 将派的正是计划里那一局。
        """
        if self._resume is None:
            return None
        planned, task_id, state = self._resume
        assert planned == episode_id, f"恢复计划是 {planned}，run 的 act 将派的却是 {episode_id}"
        self._resume, self._expect_task = None, task_id
        return state

    def save(
        self,
        level: Level,
        *,
        run_id: str,
        step: int,
        episode_id: str | None = None,
        task_id: str | None = None,
        state: RunState | None = None,
    ) -> str | None:
        """存一份 checkpoint，返回它的 id；失败时记 `checkpoint_error` 返回 None（run 照常继续）。

        run 级给 `state`（`RunState` 原件）；episode 级给 `episode_id`（将派的那一局），须在 run 的
        `act` 里调用；task 级给 `episode_id` 与 `task_id`，须在 episode 的 `act` 里调用
        （`begin_task`）。
        `step`：账的 meta 用——run / episode 级是已派局数，task 级是该 task 的 `total_acts`（快照）。
        """
        assert (state is not None) == (level == "run"), "只有 run 级给 RunState 原件"
        assert (episode_id is not None) == (level != "run"), "episode / task 级要给 episode_id"
        assert (task_id is not None) == (level == "task"), "只有 task 级给 task_id"
        if level == "task" and self._expect_task is not None:
            assert task_id == self._expect_task, (
                f"恢复后第一个开局的 task 是 {task_id}，应是 {self._expect_task}"
            )
            self._expect_task = None
        meta: dict[str, object] = {
            "source": SOURCE,
            "episode_id": episode_id if level == "task" else run_id,
            "task_id": task_id if level == "task" else run_id,
            "step": step,
        }
        prefix = f"{episode_id}.{task_id}" if level == "task" else (episode_id or run_id)
        checkpoint_id = f"{prefix}@{self.branch}-{uuid.uuid4().hex[:8]}"
        directory = self.root / run_id / checkpoint_id
        stage = "world"
        try:
            # 步骤 1：世界。
            self.game.save_state(
                FromHarnessToGameToolSaveStateReq(path=str(directory / WORLD_FILENAME))
            )
            # 步骤 2：记忆整根。
            stage = "memory"
            archive = self.memory.snapshot_memory(
                FromHarnessToMemoryToolSnapshotMemoryReq(name=checkpoint_id)
            ).archive
            # 步骤 3：图定位（episode 级只有 run 图；task 级再加 episode 图）。
            stage = "graph"
            run_ref = self._run_ref(run_id) if level != "run" else None
            episode_ref = self._episode_ref(run_ref) if run_ref and level == "task" else None
            # 步骤 4：清单。
            stage = "manifest"
            manifest = CheckpointManifest(
                checkpoint_id=checkpoint_id,
                level=level,
                run_id=run_id,
                branch=self.branch,
                episode_id=episode_id,
                task_id=task_id,
                run_state=state,
                run_ref=run_ref,
                episode_ref=episode_ref,
                world_file=WORLD_FILENAME,
                memory_archive=launch_relative(archive),
                code=self.code,
                models=self.models,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            )
            path = write_manifest(directory, manifest)
        except AssertionError:
            raise
        except Exception as exc:
            self._note(
                TraceKind.CHECKPOINT_ERROR,
                meta,
                CheckpointMark(checkpoint_id=checkpoint_id, level=level, stage=stage),
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        # 步骤 5：记账——`checkpoint_id` 进 meta，这条账就是新线的分叉点。
        self._note(
            TraceKind.CHECKPOINT_SAVE,
            {**meta, "checkpoint_id": checkpoint_id},
            CheckpointMark(level=level, manifest_path=launch_relative(path)),
        )
        return checkpoint_id

    def _run_ref(self, run_id: str) -> GraphRef:
        """run 图进 `act` 前那一条：执行 `act` 期间 run 图不写新 checkpoint，上下文里记的就是它。"""
        configurable = get_config()["configurable"]
        thread = configurable["thread_id"]
        ref = GraphRef(
            thread_id=thread, checkpoint_ns="", checkpoint_id=configurable["checkpoint_map"][""]
        )
        snapshot = self.run_graph.get_state(
            {"configurable": {"thread_id": thread, "checkpoint_id": ref.checkpoint_id}}
        )
        assert snapshot.next == ("act",), f"run 图的定位不是进 act 前：next={snapshot.next}"
        assert thread.startswith(f"{run_id}@"), f"thread {thread} 不属于 run {run_id}"
        return ref

    def _episode_ref(self, run_ref: GraphRef) -> GraphRef:
        """episode 图进 `act` 前那一条：当前命名空间（episode 的 `act` 里）去掉最后一段。

        核：saver 里这一条的父指针就是 `run_ref`，即它属于同一次 run 的 `act`。恢复时
        `resume_episode` 用 `update_state` 写进去的那一条没有父指针，只核存在——恢复路径另有
        "写入后下一格是 `act`"与"开局的就是目标 task"两道核对；
        "下一格是 `act`"由调用位置保证（`begin_task` 只在 episode 的 `act` 里被调用）。
        """
        configurable = get_config()["configurable"]
        ns = str(configurable["checkpoint_ns"])
        assert NS_SEP in ns, f"task 级存档要在 episode 的 act 里调用，当前命名空间 {ns!r}"
        episode_ns = ns.rsplit(NS_SEP, 1)[0]
        ref = GraphRef(
            thread_id=run_ref.thread_id,
            checkpoint_ns=episode_ns,
            checkpoint_id=configurable["checkpoint_map"][episode_ns],
        )
        saver = self.run_graph.checkpointer
        assert saver is not None
        saved = saver.get_tuple({"configurable": ref.model_dump()})
        assert saved is not None, f"episode 图的定位 {ref} 在 saver 里找不到"
        parents = saved.metadata.get("parents") or {}
        assert parents.get("", run_ref.checkpoint_id) == run_ref.checkpoint_id, (
            f"episode 图的定位 {ref} 不在这一次 run 的 act 里"
        )
        return ref

    def _note(
        self,
        kind: TraceKind,
        meta: dict[str, object],
        mark: CheckpointMark,
        *,
        error: str | None = None,
    ) -> None:
        """记一笔存档账。"""
        self.trace.append(
            FromHarnessToTraceToolAppendReq(kind=kind, meta=meta, checkpoint=mark, error=error)
        )


__all__ = ["SOURCE", "Checkpointer"]
