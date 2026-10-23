"""从存档恢复的用法示范：run 级、episode 级存档各恢复出一条新执行线，在图里跑到 run 结束。

**慢测试，且硬跳过**（`pytestmark = [slow, skip]`）：每个用例都跑整图 + 多次存档恢复，单个数十秒。
`slow` 让默认运行把它们排除在外；`skip` 防止有人用 `-m slow` 覆盖默认选项后误跑。
确需运行时，临时去掉下面的 `skip` 标记，本地单独跑，不提交。

一次 run 自动存两级档（`<存档根>/<run_id>/<checkpoint_id>/manifest.json`，id 形如
`<episode_id 或 run_id>@<branch>-<8 位随机 hex>`）：run 开局一份，每局开派之前（run 的 `act`
一开始）一份。恢复 = `restore_run(清单路径, 装配函数)`：装配函数只按"新分支名"装一套 runtime
（真机包一层 `build_real`，这里用假件版 `build_fake`）。新执行线与父线共用 `run_id`，
第一条账是 `checkpoint_restore`（meta 带存档 id）；父线的账一个字节都不动；新执行线上照常存档。
血缘与分支图都从账本推（`tools.trace.lineage_of` / `branch_graph`），没有别的登记表；
run/episode 恢复那条末尾还接着做分支套分支（再恢复出孙线）与逐执行线的 node_io 核对。
"""

from __future__ import annotations

import json
import pathlib

import pytest
from _fake_run import GOAL, build_fake
from _harness_fixtures import node_io

from pokemon_agent.direct.trace import branch_graph, lineage_of
from pokemon_agent.harness.checkpoint import (
    CheckpointManifest,
    list_checkpoints,
    read_manifest,
    restore_run,
)
from pokemon_agent.harness.run.run_state import RunState

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skip(reason="存档恢复慢测试：硬跳过，防止 -m slow 覆盖默认选项后误跑；需要时临时去掉本标记"),
]


def _manifests(tmp_path: pathlib.Path, branch: str = "main") -> dict[str, CheckpointManifest]:
    """某条线上的存档，按 id 的前缀取（`r1`、`r1-ep1`、`r1-ep2`；随机后缀不看）。"""
    found = {}
    for path in (tmp_path / "checkpoints" / "r1").glob("*/manifest.json"):
        manifest = read_manifest(path)
        if manifest.branch == branch:
            found[manifest.checkpoint_id.split("@")[0]] = manifest
    return found


def _branches(tmp_path: pathlib.Path) -> set[str]:
    """账本里出现过的全部执行线。"""
    trace = build_fake(tmp_path).trace
    return {json.loads(e.meta)["branch"] for e in trace.read_events({})}


def _path(tmp_path: pathlib.Path, manifest: CheckpointManifest) -> pathlib.Path:
    return tmp_path / "checkpoints" / "r1" / manifest.checkpoint_id / "manifest.json"


def _trace_bytes(tmp_path: pathlib.Path) -> dict[str, bytes]:
    root = tmp_path / "trace"
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _build_branch(tmp_path: pathlib.Path):
    """装配函数：新执行线用同一个存档根与 trace 根，只换分支名。"""

    def build(branch: str):
        return build_fake(tmp_path, checkpoints=True, branch=branch).run_rt

    return build


def test_a_run_saves_at_its_start_before_each_episode_and_before_each_task(
    tmp_path: pathlib.Path,
) -> None:
    """run 级存 `RunState` 原件；episode 级记 run 图进 `act` 前那条的位置；task 级再记 episode 图
    进 `act` 前那条。每个 task 的存档账都排在它的 `task_start` 之前。"""
    fake = build_fake(tmp_path, checkpoints=True)
    fake.harness.run("r1", [GOAL])
    manifests = _manifests(tmp_path)
    assert {k for k, m in manifests.items() if m.level != "task"} == {"r1", "r1-ep1", "r1-ep2"}
    run_level = manifests["r1"]
    assert isinstance(run_level.run_state, RunState) and run_level.run_ref is None
    ep2 = manifests["r1-ep2"]
    assert ep2.level == "episode" and ep2.episode_id == "r1-ep2"
    assert ep2.run_ref is not None and ep2.run_ref.thread_id == "r1@main"

    # task 级：两张图的定位都在，episode 图的命名空间在 run 的 act 里。
    tasks = [m for m in manifests.values() if m.level == "task"]
    assert tasks
    for task in tasks:
        assert task.run_ref is not None and task.episode_ref is not None
        assert task.episode_ref.checkpoint_ns.startswith("act:")
        assert task.checkpoint_id.startswith(f"{task.episode_id}.{task.task_id}@main-")

    # 账序：每个 task 的 checkpoint_save 紧挨在它的 task_start 前面。
    events = fake.trace.read_events({"run_id": "r1", "branch": "main"})
    starts = [i for i, e in enumerate(events) if e.kind == "task_start"]
    assert len(starts) == len(tasks)
    for i in starts:
        before, start = events[i - 1], events[i]
        assert before.kind == "checkpoint_save"
        assert json.loads(before.meta)["task_id"] == json.loads(start.meta)["task_id"]


def test_run_and_episode_saves_restore_into_new_branches(tmp_path: pathlib.Path) -> None:
    """main 跑完后，从 run 开局与第 2 局开派前各恢复一次，各得一条新线，都跑到 run 结束；
    再从新线自己的存档恢复出孙线（分支套分支），三条执行线按血缘拼好后逐格核对。"""
    # 步骤 1：main 跑一个完整 run，存档自动落下。
    main = build_fake(tmp_path, checkpoints=True)
    main.harness.run("r1", [GOAL])
    manifests = _manifests(tmp_path)
    before = _trace_bytes(tmp_path)
    main_events = main.trace.read_events({"run_id": "r1", "branch": "main"})
    main_uuids = {e.uuid for e in main_events}

    for prefix in ("r1", "r1-ep2"):
        manifest = manifests[prefix]
        known = _branches(tmp_path)

        # 步骤 2：恢复，跑到 run 结束；新线名是随机的。
        outcomes, *_ = restore_run(_path(tmp_path, manifest), _build_branch(tmp_path))
        assert outcomes, f"{prefix} 恢复后没有跑出任何 episode"
        (branch,) = _branches(tmp_path) - known

        # 步骤 3：新线自己的账：第一条是恢复账，meta 带存档 id；之后每局开派前照常存档。
        own = main.trace.read_events({"run_id": "r1", "branch": branch})
        assert own[0].kind == "checkpoint_restore"
        assert json.loads(own[0].meta)["checkpoint_id"] == manifest.checkpoint_id
        saved = [json.loads(e.meta)["checkpoint_id"] for e in own if e.kind == "checkpoint_save"]
        assert saved and all(f"@{branch}-" in cid for cid in saved)

        # 步骤 4：血缘从账本推出——父线是 main，分叉点是 main 上这份存档的 checkpoint_save。
        (fork,) = lineage_of(main.trace.read_events({}), branch)
        save = next(
            e
            for e in main_events
            if json.loads(e.meta).get("checkpoint_id") == manifest.checkpoint_id
        )
        assert (fork.branch, fork.checkpoint_id) == ("main", manifest.checkpoint_id)
        assert fork.seq == save.seq

        # 步骤 5：按血缘读——main 截至分叉点（含）+ 自己的账。
        seen = build_fake(tmp_path, branch=branch).trace.read_events({"run_id": "r1"})
        inherited = [e for e in seen if e.uuid in main_uuids]
        assert inherited[-1].uuid == save.uuid
        assert len(seen) == len(inherited) + len(own)

    # 步骤 6：分支图两条边都挂在 main 上；父线的账一个字节都没动。
    edges = branch_graph(main.trace.read_events({}), "r1")
    assert [(e.parent, e.checkpoint_id) for e in edges] == [
        ("main", manifests["r1"].checkpoint_id),
        ("main", manifests["r1-ep2"].checkpoint_id),
    ]
    after = _trace_bytes(tmp_path)
    assert all(after[name] == data for name, data in before.items())

    # 步骤 7：分支套分支——从 b1（循环最后一轮 "r1-ep2" 恢复出的新线）自己的第 2 局存档
    # 再恢复出 b2；b2 的血缘由近到远是 b1、main。
    b1 = branch
    b1_ep2 = _manifests(tmp_path, b1).get("r1-ep2")
    assert b1_ep2 is not None, "b1 上没有存下自己的 episode 存档"
    known_before_b2 = _branches(tmp_path)
    restore_run(_path(tmp_path, b1_ep2), _build_branch(tmp_path))
    (b2,) = _branches(tmp_path) - known_before_b2

    # 步骤 8：三条执行线（b1、b2、main）按血缘拼好，逐格核对照样走得通。
    trace = build_fake(tmp_path).trace
    assert [f.branch for f in lineage_of(trace.read_events({}), b2)] == [b1, "main"]
    events = [json.loads(e.model_dump_json()) for e in trace.read_events({})]
    for line in (b1, b2, "main"):
        view = node_io.branch_view(events, line)
        node_io.check_run_markers(view)
        node_io.check_vocabulary(view)
        node_io.check_payloads(view)
        node_io.check_layer_flow(view)
        node_io.check_run_invariants(view)
        for episode_id in node_io.episode_ids(view):
            node_io.check_node_coverage(view, episode_id)
            node_io.check_content_invariants(view, episode_id)


def test_a_task_save_restores_straight_into_that_task(tmp_path: pathlib.Path) -> None:
    """从第 1 局第 2 个 task 的存档恢复：run、episode 两张图在图内回到进 `act` 前，
    不重跑已完成的 task，直接从这个 task 开局接着跑到 run 结束。"""
    # 步骤 1：main 跑完；挑第 1 局第 2 个 task 开局那份存档（`list_checkpoints` 按创建先后列出）。
    main = build_fake(tmp_path, checkpoints=True)
    main.harness.run("r1", [GOAL])
    before = _trace_bytes(tmp_path)
    tasks = [
        m
        for m in list_checkpoints(tmp_path / "checkpoints", "r1")
        if m.level == "task" and m.episode_id == "r1-ep1"
    ]
    assert len(tasks) >= 2
    target = tasks[1]

    # 步骤 2：恢复并跑到底。
    known = _branches(tmp_path)
    outcomes, *_ = restore_run(_path(tmp_path, target), _build_branch(tmp_path))
    assert outcomes
    (branch,) = _branches(tmp_path) - known

    # 步骤 3：新线的账：恢复账 → 目标 task 的存档账 → 目标 task 的开局账；这一局不重开。
    own = main.trace.read_events({"run_id": "r1", "branch": branch})
    assert [e.kind for e in own[:3]] == ["checkpoint_restore", "checkpoint_save", "task_start"]
    assert json.loads(own[1].meta)["task_id"] == target.task_id
    assert json.loads(own[2].meta)["task_id"] == target.task_id
    first_episode_starts = [
        e for e in own if e.kind == "episode_start" and json.loads(e.meta)["episode_id"] == "r1-ep1"
    ]
    assert first_episode_starts == [], "恢复出来的线不该重开第 1 局"

    # 步骤 4：按血缘读，第 1 局的开局账与目标 task 的开局账各只一条（父线的在分叉点之前）。
    seen = build_fake(tmp_path, branch=branch).trace.read_events({"run_id": "r1"})

    def count(kind: str, **where: str) -> int:
        return sum(
            1
            for e in seen
            if e.kind == kind
            and all(json.loads(e.meta).get(key) == value for key, value in where.items())
        )

    assert count("episode_start", episode_id="r1-ep1") == 1
    assert count("task_start", episode_id="r1-ep1", task_id=target.task_id) == 1

    # 步骤 5：按血缘拼好后逐格核对照样走得通；父线的账一个字节都没动。
    events = [json.loads(e.model_dump_json()) for e in main.trace.read_events({})]
    view = node_io.branch_view(events, branch)
    node_io.check_run_markers(view)
    node_io.check_vocabulary(view)
    node_io.check_payloads(view)
    node_io.check_layer_flow(view)
    node_io.check_run_invariants(view)
    after = _trace_bytes(tmp_path)
    assert all(after[name] == data for name, data in before.items())
