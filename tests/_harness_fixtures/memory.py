"""用假大脑 / 假世界 / 假记忆把**真的三张图**跑一遍，交回落盘账本——给 `test_node_io.py` 当样本。

图、harness、`TraceTool` 渲染与落盘都是真的；只有模型、PyBoy、记忆库是假的。
这样核对脚本面对的是**真实形状**的账，而不是手写的近似品：harness 改了发账顺序，
这里立刻跟着变。

三个判定按目标文字分层：task 的目标恒为 `SUBTASK`，run 的目标以"依次完成"开头，
其余是 episode 的目标。每层给一个"第 n 次被问时判不判完成"的函数。
"""

from __future__ import annotations

import pickle
import time
from collections.abc import Callable
from pathlib import Path

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizedRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolRestoreMemoryResp,
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryResp,
)
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory

SUBTASK = "子任务"
"""假拆解给出的每个 task 的目标文字（task 层判定据此认出自己）。"""

_MOCK_DELAY_SECONDS = 0.003
"""每个假件返回前垫的延迟（2026-09-27）。

目的有二：让 rehearsal/测试里的账本带上**非零的真实形状**——模型账的
payload 双时刻（真 `brain.py` 在 provider 前后取时，假件在这里同形盖戳，
练的是 `render._payload_time` 提取路径）与检索 req 的计时字段不再是 0；
也让 UI 时间线上相邻的账拉开一点间隔。
"""

Policy = Callable[[int], bool]
"""第 n 次（从 1 起）被问"完成了没有"时的回答。"""


class _Memory:
    """只记在内存里的记忆库；快照把三张表 pickle 进 `<snapshot_dir>/<name>.pkl`。"""

    def __init__(self, snapshot_dir: Path | None = None) -> None:
        self.acts: list = []
        self.tasks: list = []
        self.episodes: list = []
        self._snapshot_dir = snapshot_dir

    def snapshot_memory(
        self, req: FromHarnessToMemoryToolSnapshotMemoryReq
    ) -> FromHarnessToMemoryToolSnapshotMemoryResp:
        assert self._snapshot_dir is not None, "这份假记忆没给快照目录"
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self._snapshot_dir / f"{req.name}.pkl"
        path.write_bytes(pickle.dumps((self.acts, self.tasks, self.episodes)))
        return FromHarnessToMemoryToolSnapshotMemoryResp(archive=str(path))

    def restore_memory(
        self, req: FromHarnessToMemoryToolRestoreMemoryReq
    ) -> FromHarnessToMemoryToolRestoreMemoryResp:
        self.acts, self.tasks, self.episodes = pickle.loads(Path(req.archive).read_bytes())
        return FromHarnessToMemoryToolRestoreMemoryResp(
            unpacked=len(self.acts) + len(self.tasks) + len(self.episodes)
        )

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        time.sleep(_MOCK_DELAY_SECONDS)
        items: list = []
        episode_id = req.conditions.get("episode_id")
        if episode_id:
            items += [
                {
                    "kind": "act",
                    "uuid": f"a{i}",
                    "score": None,
                    "content": a.action,
                    "payload": a.model_dump(),
                }
                for i, a in enumerate(self.acts)
                if a.episode_id == episode_id
            ]
            items += [
                {
                    "kind": "task",
                    "uuid": f"t{i}",
                    "score": None,
                    "content": m.summary,
                    "payload": m.model_dump(),
                }
                for i, m in enumerate(self.tasks)
                if m.episode_id == episode_id
            ]
        if req.conditions:
            hits = [
                m
                for m in self.episodes
                if all(getattr(m, k) == v for k, v in req.conditions.items())
            ]
            items += [
                {
                    "kind": "episode",
                    "uuid": f"e{i}",
                    "score": None,
                    "content": m.markdown,
                    "payload": m.model_dump(exclude={"markdown"}),
                }
                for i, m in enumerate(hits)
            ]
        return FromHarnessToMemoryToolRecallResp(
            items=[FromHarnessToMemoryToolRecallItem(**item) for item in items]
        )

    def memorize(
        self, req: FromHarnessToMemoryToolMemorizeReq
    ) -> FromHarnessToMemoryToolMemorizeResp:
        stored = []
        for record in req.records:
            uuid_ = f"{record.kind}-{len(self.acts) + len(self.tasks) + len(self.episodes)}"
            if record.kind == "act":
                self.acts.append(ActMemory.model_validate(record.payload))
            elif record.kind == "task":
                self.tasks.append(TaskMemory.model_validate(record.payload))
            elif record.kind == "episode":
                self.episodes.append(EpisodeMemory(**record.payload))
            stored.append(FromHarnessToMemoryToolMemorizedRecord(kind=record.kind, uuid=uuid_))
            if self._snapshot_dir is not None:
                root = self._snapshot_dir / "records"
                root.mkdir(parents=True, exist_ok=True)
                (root / f"{uuid_}.json").write_text(record.model_dump_json(), encoding="utf-8")
        return FromHarnessToMemoryToolMemorizeResp(stored=stored)
