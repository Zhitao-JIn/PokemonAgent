"""执行线的血缘与分支图：从账本里的 `checkpoint_restore` / `checkpoint_save` 推出来（spec §六）。

新线的第一条账 `checkpoint_restore` 的 meta 带 `checkpoint_id`；同 id 的 `checkpoint_save`
记在父线上——它的 `branch` 就是父线，它自己的 `(ts, uuid)` 就是分叉点。账本之外不另存分支登记。

两个函数都只收一份读回来的账（`TraceTool.read_events({})` 或存储层的全量读），在内存里筛，
不认识存储。

**宽容边界（0929 定案）**：restore 账指向的 save 账**不在本账本**（跨账本存档——如 eval
预打包的起点，save 在打包 trace 里；或账本被清过）时，记 warning 并**按世界起点处理**
（祖先历史不可见，跑照跑）——只在 save/restore 数量对不上（重复、成环）时才 LookupError，
那才是账本真坏了。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pokemon_agent.schemas.harness import TraceKind

logger = logging.getLogger(__name__)


class _Entry(Protocol):
    """读回的一条账里本文件用到的四样。"""

    uuid: str
    ended_at: float
    kind: str
    meta: str


@dataclass(frozen=True)
class Fork:
    """血缘的一环：父线（`run_id` + `branch`）与分叉点（父线上那条 `checkpoint_save`）。"""

    run_id: str
    branch: str
    checkpoint_id: str
    ended_at: float
    seq: int


@dataclass(frozen=True)
class BranchEdge:
    """分支图的一条边：`child` 从 `parent` 上的存档 `checkpoint_id` 处分出。"""

    child: str
    parent: str
    checkpoint_id: str
    fork_ended_at: float
    fork_seq: int


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
        # 步骤 2：同 id 的存档账——它在哪条线上，那条线就是父线；不在账本 → 世界起点，到头。
        save, meta = _the_save(tagged, checkpoint_id)
        if save is None:
            return chain
        parent = str(meta["branch"])
        if parent in seen:
            raise LookupError(f"执行线 {branch} 的血缘成环：{parent}")
        chain.append(Fork(str(meta["run_id"]), parent, checkpoint_id, save.ended_at, save.seq))
        seen.add(parent)
        branch = parent


def branch_graph(events: Sequence[_Entry], run_id: str) -> list[BranchEdge]:
    """本 run 的分支图：每条 `checkpoint_restore` 一条边，按恢复发生的先后排。"""
    tagged = [(event, json.loads(event.meta)) for event in events]
    edges: list[BranchEdge] = []
    for event, meta in sorted(tagged, key=lambda pair: (pair[0].ended_at, pair[0].seq)):
        if event.kind != TraceKind.CHECKPOINT_RESTORE or meta.get("run_id") != run_id:
            continue
        checkpoint_id = str(meta["checkpoint_id"])
        save, save_meta = _the_save(tagged, checkpoint_id)
        if save is None:
            continue
        edges.append(
            BranchEdge(
                child=str(meta["branch"]),
                parent=str(save_meta["branch"]),
                checkpoint_id=checkpoint_id,
                fork_ended_at=save.ended_at,
                fork_seq=save.seq,
            )
        )
    return edges


def _the_save(
    tagged: Sequence[tuple[_Entry, dict]], checkpoint_id: str
) -> tuple[_Entry | None, dict | None]:
    """`checkpoint_id` 那份存档的 `checkpoint_save`（连同解开的 meta）。

    save 不在本账本（跨账本存档/账本清过）→ warning + `(None, None)`，调用方按世界起点
    处理；save 重复（>1 条）→ LookupError——那意味着同一份存档被打包了两次，账本真坏了。
    """
    saves = [
        (event, meta)
        for event, meta in tagged
        if event.kind == TraceKind.CHECKPOINT_SAVE and meta.get("checkpoint_id") == checkpoint_id
    ]
    if not saves:
        logger.warning(
            "存档 %s 的 checkpoint_save 不在本账本——按世界起点处理，祖先历史不可见",
            checkpoint_id,
        )
        return None, None
    if len(saves) > 1:
        raise LookupError(f"存档 {checkpoint_id} 的 checkpoint_save 有 {len(saves)} 条，应恰好一条")
    return saves[0]


__all__ = ["BranchEdge", "Fork", "branch_graph", "lineage_of"]
