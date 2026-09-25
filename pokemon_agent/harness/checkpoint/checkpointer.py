"""`Checkpointer`：两级存档 + task 世界快照 + 封存本局的账（spec v2 §二、§五）。

存档点由调用方显式调用：
- `save()`：run 级在 `run_entry.new_run`（reset 之后、进图之前），episode 级在 run 的 `act` 一开始
  （进 `act` 前的那份状态）。两处都不嵌在任何 `act` 里：run 级传 `RunState` 原件；episode 级只记
  run 图"进 `act` 前"那条 checkpoint 的位置——它是根图，执行上下文里的 `checkpoint_map[""]` 就是它。
- `snapshot_world()`：每个 task 开局（`begin_task` 末尾）只存世界，按执行线分开（intent C15）。
- `seal_episode()`：这一局结束（或 run 出错）时，把"本局存档之后"的账复制进本局存档的
  `trace@<branch>/`，存档自带回放要用的账（intent C14）。从半路回放出来的执行线没有这一局
  自己的存档，恢复路径在切换时用 `open_episode()` 指定"这一局的起点存档"，封进它那里。

回放段里 `paused` 为真：三个存档点一律不存、不记账（那一份与父线已有的相同，intent C16）。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from langgraph.config import get_config
from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import CheckpointMark
from pokemon_agent.tools.interface import GameToolPort, MemoryToolPort, TraceToolPort

from ..run.run_state import RunState
from .manifest import (
    WORLD_FILENAME,
    CheckpointManifest,
    GraphRef,
    Level,
    LineageLink,
    code_stamp,
    launch_relative,
    write_manifest,
)

SOURCE = "checkpoint.save"
WORLDS_DIRNAME = "worlds"
SEALED_PREFIX = "trace@"


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
        lineage: Sequence[LineageLink] = (),
        models: dict[str, str] | None = None,
    ) -> None:
        """root：存档根（`<root>/<run_id>/<checkpoint_id>/`）。

        run_graph：挂着 saver 的 run 图（episode 级存档核定位、恢复时读值都经它）。
        branch / lineage：本执行线与其祖先（由根到父）。
        """
        assert branch, "Checkpointer needs a non-empty branch"
        assert run_graph.checkpointer is not None, "run 图必须挂 saver 才能存档"
        self.root = Path(root)
        self.run_graph = run_graph
        self.game = game
        self.memory = memory
        self.trace = trace
        self.branch = branch
        self.lineage = list(lineage)
        self.models = dict(models or {})
        self.code = code_stamp()
        self._open: CheckpointManifest | None = None
        """本执行线这一局的起点存档（它那一局的账还没封存）。"""
        self.paused = False
        """回放段里为真：存档点一律不存、不记账。"""

    def save(self, *, level: Level, state: RunState, episode_id: str | None = None) -> str | None:
        """存一份 checkpoint，返回它的 id；失败时记 `checkpoint_error` 返回 None（run 照常继续）。

        前置条件：run 级不给 `episode_id`；episode 级给出将派的那一局，且必须在 run 图执行 `act`
        的上下文里调用。
        """
        assert (level == "episode") == (episode_id is not None)
        if self.paused:
            return None
        run_id = state.run_id
        meta = _meta(state)
        checkpoint_id = self._new_id(run_id, episode_id)
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
            archive = launch_relative(archive)
            # 步骤 3：run 图定位（episode 级）。
            stage = "graph"
            run_ref = self._run_ref(run_id) if level == "episode" else None
            # 步骤 4：分叉点——本执行线此刻的最后一条账（run 级存档时还没开账）。
            seen = self.trace.read_events({"run_id": run_id})
            last_uuid, last_ts = (seen[-1].uuid, seen[-1].ts) if seen else ("", 0.0)
            # 步骤 5：清单。
            stage = "manifest"
            manifest = CheckpointManifest(
                checkpoint_id=checkpoint_id,
                level=level,
                run_id=run_id,
                branch=self.branch,
                lineage=self.lineage,
                episode_id=episode_id,
                run_state=state if level == "run" else None,
                run_ref=run_ref,
                world_file=WORLD_FILENAME,
                memory_archive=archive,
                last_event_uuid=last_uuid,
                last_event_ts=last_ts,
                code=self.code,
                models=self.models,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            )
            path = write_manifest(directory, manifest)
            if level == "episode":
                self._open = manifest
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
        # 步骤 6：记账。
        self._note(
            TraceKind.CHECKPOINT_SAVE,
            meta,
            CheckpointMark(
                checkpoint_id=checkpoint_id, level=level, manifest_path=launch_relative(path)
            ),
        )
        return checkpoint_id

    def snapshot_world(self, *, run_id: str, episode_id: str, task_id: str, step: int) -> None:
        """task 开局存一份世界（`worlds/<ep>/<task_id>@<branch>.state`），记 `world_snapshot`。

        失败只记 `checkpoint_error`（stage `world_snapshot`），run 照常继续。
        """
        if self.paused:
            return
        meta = {"source": SOURCE, "episode_id": episode_id, "task_id": task_id, "step": step}
        path = self._free(
            self.root / run_id / WORLDS_DIRNAME / episode_id / f"{task_id}@{self.branch}"
        )
        try:
            self.game.save_state(FromHarnessToGameToolSaveStateReq(path=str(path)))
        except Exception as exc:
            self._note(
                TraceKind.CHECKPOINT_ERROR,
                meta,
                CheckpointMark(level="task", stage="world_snapshot"),
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._note(
            TraceKind.WORLD_SNAPSHOT,
            meta,
            CheckpointMark(level="task", world_path=launch_relative(path)),
        )

    def seal_episode(self, *, run_id: str, step: int) -> None:
        """把这一局起点存档之后、本执行线的账逐条写进该存档的 `trace@<branch>/`，记 `trace_sealed`。

        没有待封的（存档关着、存档失败、已封过、回放段里）就不做。失败只记 `checkpoint_error`。
        """
        if self.paused:
            return
        manifest, self._open = self._open, None
        if manifest is None:
            return
        meta = {"source": SOURCE, "episode_id": run_id, "task_id": run_id, "step": step}
        fork = (manifest.last_event_ts, manifest.last_event_uuid)
        directory = self.root / run_id / manifest.checkpoint_id / f"{SEALED_PREFIX}{self.branch}"
        try:
            events = [
                e for e in self.trace.read_events({"run_id": run_id}) if (e.ts, e.uuid) > fork
            ]
            directory.mkdir(parents=True, exist_ok=True)
            for event in events:
                (directory / f"{event.uuid}.json").write_text(
                    event.model_dump_json(), encoding="utf-8"
                )
        except Exception as exc:
            self._note(
                TraceKind.CHECKPOINT_ERROR,
                meta,
                CheckpointMark(checkpoint_id=manifest.checkpoint_id, level="episode", stage="seal"),
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._note(
            TraceKind.TRACE_SEALED,
            meta,
            CheckpointMark(
                checkpoint_id=manifest.checkpoint_id, level="episode", count=len(events)
            ),
        )

    def open_episode(self, manifest: CheckpointManifest) -> None:
        """指定这一局的起点存档（回放切换时用：新执行线这一局没有自己的存档）。"""
        assert manifest.level == "episode"
        self._open = manifest

    def _free(self, stem: Path) -> Path:
        """`<stem>.state`，已存在则 `<stem>-2.state`、`-3`…"""
        candidate, n = stem.with_name(f"{stem.name}.state"), 1
        while candidate.exists():
            n += 1
            candidate = stem.with_name(f"{stem.name}-{n}.state")
        return candidate

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

    def _new_id(self, run_id: str, episode_id: str | None) -> str:
        """`<run_id>` / `<episode_id>`，再接 `@<branch>`；重名时加 `-2`、`-3`…"""
        base = f"{episode_id or run_id}@{self.branch}"
        candidate, n = base, 1
        while (self.root / run_id / candidate).exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

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


def _meta(state: RunState) -> dict[str, object]:
    """存档账的签名：两级都是 run 层的账（episode 级存档时这一局还没开）——`episode_id` / `task_id`
    位放 run_id，`step` = 已派局数。"""
    return {
        "source": SOURCE,
        "episode_id": state.run_id,
        "task_id": state.run_id,
        "step": state.step,
    }


__all__ = ["SOURCE", "Checkpointer"]
