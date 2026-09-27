"""执行线的血缘与分支图：从账本里的 `checkpoint_restore` / `checkpoint_save` 推出来（spec §六）。

新线的第一条账 `checkpoint_restore` 的 meta 带 `checkpoint_id`；同 id 的 `checkpoint_save`
记在父线上——它的 `branch` 就是父线，它自己的 `(ts, uuid)` 就是分叉点。账本之外不另存分支登记。

两个函数都只收一份读回来的账（`TraceTool.read_events({})` 或存储层的全量读），在内存里筛，
不认识存储。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pokemon_agent.schemas.harness import TraceKind


class _Entry(Protocol):
    """读回的一条账里本文件用到的四样。"""

    uuid: str
    ts: float
    kind: str
    meta: str


@dataclass(frozen=True)
class Fork:
    """血缘的一环：父线（`run_id` + `branch`）与分叉点（父线上那条 `checkpoint_save`）。"""

    run_id: str
    branch: str
    checkpoint_id: str
    ts: float
    uuid: str


@dataclass(frozen=True)
class BranchEdge:
    """分支图的一条边：`child` 从 `parent` 上的存档 `checkpoint_id` 处分出。"""

    child: str
    parent: str
    checkpoint_id: str
    fork_ts: float
    fork_uuid: str


def lineage_of(events: Sequence[_Entry], branch: str) -> list[Fork]:
    """`branch` 的祖先，由近到远；没有 `checkpoint_restore` 的线（如 `main`）没有祖先。

    失败：某条线的恢复账多于一条、或对不上恰好一条 `checkpoint_save` → `LookupError`（账本坏了）。
    """
    tagged = [(event, json.loads(event.meta)) for event in events]
    chain: list[Fork] = []
    seen = {branch}
    while True:
        # 步骤 1：本线的恢复账；没有就到头了。
        restores = [
            meta
            for event, meta in tagged
            if event.kind == TraceKind.CHECKPOINT_RESTORE and meta.get("branch") == branch
        ]
        if not restores:
            return chain
        if len(restores) > 1:
            raise LookupError(f"执行线 {branch} 有 {len(restores)} 条 checkpoint_restore")
        checkpoint_id = str(restores[0]["checkpoint_id"])
        # 步骤 2：同 id 的存档账——它在哪条线上，那条线就是父线。
        save, meta = _the_save(tagged, checkpoint_id)
        parent = str(meta["branch"])
        if parent in seen:
            raise LookupError(f"执行线 {branch} 的血缘成环：{parent}")
        chain.append(Fork(str(meta["run_id"]), parent, checkpoint_id, save.ts, save.uuid))
        seen.add(parent)
        branch = parent


def branch_graph(events: Sequence[_Entry], run_id: str) -> list[BranchEdge]:
    """本 run 的分支图：每条 `checkpoint_restore` 一条边，按恢复发生的先后排。"""
    tagged = [(event, json.loads(event.meta)) for event in events]
    edges: list[BranchEdge] = []
    for event, meta in sorted(tagged, key=lambda pair: (pair[0].ts, pair[0].uuid)):
        if event.kind != TraceKind.CHECKPOINT_RESTORE or meta.get("run_id") != run_id:
            continue
        checkpoint_id = str(meta["checkpoint_id"])
        save, save_meta = _the_save(tagged, checkpoint_id)
        edges.append(
            BranchEdge(
                child=str(meta["branch"]),
                parent=str(save_meta["branch"]),
                checkpoint_id=checkpoint_id,
                fork_ts=save.ts,
                fork_uuid=save.uuid,
            )
        )
    return edges


def _the_save(tagged: Sequence[tuple[_Entry, dict]], checkpoint_id: str) -> tuple[_Entry, dict]:
    """`checkpoint_id` 那份存档的 `checkpoint_save`（连同解开的 meta），必须恰好一条。"""
    saves = [
        (event, meta)
        for event, meta in tagged
        if event.kind == TraceKind.CHECKPOINT_SAVE and meta.get("checkpoint_id") == checkpoint_id
    ]
    if len(saves) != 1:
        raise LookupError(f"存档 {checkpoint_id} 的 checkpoint_save 有 {len(saves)} 条，应恰好一条")
    return saves[0]


__all__ = ["BranchEdge", "Fork", "branch_graph", "lineage_of"]
