"""按分支血缘读账的用法示范：恢复出来的执行线看得见"父线分叉点及之前的账 + 自己的账"。

一条执行线 = 一个 `branch`（未经恢复为 `"main"`）。`TraceTool.build(branch=…)` 只给分支名；
血缘从账本里推：新线第一条账 `checkpoint_restore` 的 meta 带 `checkpoint_id`，父线上同 id 的
`checkpoint_save` 就是分叉点（它在哪条线上，那条线就是父线）。分支图也从这两本账画出来。
"""

from __future__ import annotations

import json
import pathlib

from pokemon_agent.direct.trace import TraceTool, branch_graph, lineage_of
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import CheckpointMark

META = {"source": "test", "episode_id": "r1-ep1", "task_id": "r1-ep1"}


def _step(step: int) -> FromHarnessToTraceToolAppendReq:
    """一笔最小的账：本局第 `step` 步推进。"""
    return FromHarnessToTraceToolAppendReq(
        kind=TraceKind.ADVANCE_STEP, meta={**META, "step": step}, next_step=step + 1
    )


def _save(checkpoint_id: str, step: int) -> FromHarnessToTraceToolAppendReq:
    """存档账：meta 带 `checkpoint_id`——从它恢复出的新线就在这一条处分叉。"""
    return FromHarnessToTraceToolAppendReq(
        kind=TraceKind.CHECKPOINT_SAVE,
        meta={**META, "step": step, "checkpoint_id": checkpoint_id},
        checkpoint=CheckpointMark(level="episode", manifest_path=f"{checkpoint_id}/manifest.json"),
    )


def _restore(checkpoint_id: str, step: int) -> FromHarnessToTraceToolAppendReq:
    """恢复账：新线的第一条，meta 带它从哪份存档恢复。"""
    return FromHarnessToTraceToolAppendReq(
        kind=TraceKind.CHECKPOINT_RESTORE,
        meta={**META, "step": step, "checkpoint_id": checkpoint_id},
        checkpoint=CheckpointMark(level="episode", manifest_path=f"{checkpoint_id}/manifest.json"),
    )


def _steps(tool: TraceTool) -> list[tuple[str, int]]:
    """这条执行线看得见的推进账，返回 `(分支, 步号)`。"""
    return [
        (json.loads(e.meta)["branch"], json.loads(e.meta)["step"])
        for e in tool.read_events({"run_id": "r1"})
        if e.kind == TraceKind.ADVANCE_STEP
    ]


def test_a_restored_branch_sees_its_ancestors_up_to_each_fork(tmp_path: pathlib.Path) -> None:
    """main 走到第 2 步存档 A，从 A 恢复出 b1；b1 走一步存档 B，从 B 恢复出 b2。

    各自之后的账互不可见。
    """
    # 步骤 1：main 跑两步，存档 A，继续跑一步。
    main = TraceTool.build(run_id="r1", trace_root=tmp_path)
    main.append(_step(1))
    main.append(_step(2))
    main.append(_save("A", 2))
    main.append(_step(3))

    # 步骤 2：b1 只知道自己的名字；第一条账说"从 A 恢复"，跑一步后存档 B，再跑一步。
    b1 = TraceTool.build(run_id="r1", trace_root=tmp_path, branch="b1")
    b1.append(_restore("A", 2))
    b1.append(_step(3))
    b1.append(_save("B", 3))
    b1.append(_step(4))

    # 步骤 3：b2 从 B 恢复。
    b2 = TraceTool.build(run_id="r1", trace_root=tmp_path, branch="b2")
    b2.append(_restore("B", 3))
    b2.append(_step(4))

    assert _steps(main) == [("main", 1), ("main", 2), ("main", 3)]
    assert sorted(_steps(b1)) == sorted([("main", 1), ("main", 2), ("b1", 3), ("b1", 4)])
    assert sorted(_steps(b2)) == sorted([("main", 1), ("main", 2), ("b1", 3), ("b2", 4)])
    for tool in (main, b1, b2):
        events = tool.read_events({"run_id": "r1"})
        keys = [(event.ended_at, event.seq) for event in events]
        assert keys == sorted(keys)

    # 步骤 4：血缘由近到远；分支图每条恢复账一条边。
    everything = main.read_events({})
    assert [(f.branch, f.checkpoint_id) for f in lineage_of(everything, "b2")] == [
        ("b1", "B"),
        ("main", "A"),
    ]
    assert [(e.child, e.parent, e.checkpoint_id) for e in branch_graph(everything, "r1")] == [
        ("b1", "main", "A"),
        ("b2", "b1", "B"),
    ]


def test_asking_for_a_branch_explicitly_skips_the_lineage(tmp_path: pathlib.Path) -> None:
    """`meta` 自带 `branch` 时按调用方给的读，不拼血缘；`meta` 为空时整个落盘根原样返回。"""
    main = TraceTool.build(run_id="r1", trace_root=tmp_path)
    main.append(_step(1))
    main.append(_save("A", 1))
    b1 = TraceTool.build(run_id="r1", trace_root=tmp_path, branch="b1")
    b1.append(_restore("A", 1))
    b1.append(_step(2))

    own = b1.read_events({"branch": "b1"})
    assert [e.kind for e in own] == [TraceKind.CHECKPOINT_RESTORE, TraceKind.ADVANCE_STEP]
    assert len(b1.read_events()) == 4
