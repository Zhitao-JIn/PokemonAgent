"""维度 5（restore）：真实跨进程 checkpoint 恢复——load → void_after → 续跑。

前面的维度都只查"落盘产物长什么样"，没有任何脚本真正走过**读回路径**。
本脚本补上恢复链路的真实执行：

  阶段 A  build_real 完整跑一个 3 步 run（生成 trace / checkpoint / 记忆产物）；
  阶段 B  模拟"崩溃后重启"：读 run.json 拿事件游标 → 带 `resume_cursor` 重新
          build_real（新进程语义：trace 从游标 +1 续写）→
          `resume_run(run_id, episode_id, step)` 走
          取存档 → 废弃时间线归档 → 世界快照回载 → 状态重建 → 续跑到收尾。

通过判定（全部独立可判）：
  1. 阶段 B 返回 `RunOutcomeResp`；
  2. 恢复后 trace 里出现 `checkpoint_restore` 事件且 `restored_step` 对得上；
  3. 恢复后全部事件按 event_id 全局排序仍严格连续（无缺号无重号——
     废弃归档截掉游标后的段，新事件必须从游标 +1 无缝续写）；
  4. `voided-*/` 归档目录真实生成（废弃时间线处理真的发生了）。

跑完后把 last-run 指针指向恢复后的时间线，维度 2/3/4 可以直接对它复核。
前置条件：`ARK_API_KEY` 与 `DASHSCOPE_API_KEY` 都要有。
"""

from __future__ import annotations

import json
import time


def main() -> None:
    from pokemon_agent.build import build_real
    from pokemon_agent.experiment.real_check.common import (
        GOAL,
        ROM,
        STATE,
        STEPS,
        SUCCESS_CRITERIA,
        TRACE_ROOT,
        make_review_pair,
        safe,
        write_last_run,
    )
    from pokemon_agent.schemas.domain import TaskForHarness

    run_id = f"restorecheck-{time.strftime('%m%d-%H%M%S')}"
    task = TaskForHarness(
        task_id="restorecheck",
        goal=GOAL,
        success_criteria=SUCCESS_CRITERIA,
        max_steps=STEPS,
    )

    # ---- 阶段 A：完整跑一遍，生成存档 ----
    # 两个开关全关 + DataCenterReviewer：plan 跳过模型调用，栈清空后交
    # 人工审查，没前端等 REVIEW_TIMEOUT 秒按 STOP 收场（同 check_harness）。
    print(f"[A1/8] build_real 装配中（run_id={run_id}）...", flush=True)
    data_center, reviewer = make_review_pair()
    harness, _trace, world, _tools = build_real(
        ROM,
        STATE,
        run_id=run_id,
        reviewer=reviewer,
        data_center=data_center,
        auto_push_goals=False,
        auto_decide_done=False,
    )
    print("[A2/8] build_real 完成。", flush=True)
    try:
        print("[A3/8] harness.run 开始（3 步短目标）...", flush=True)
        result = harness.run(run_id, [task])
        print("[A4/8] harness.run 完成。", flush=True)
    finally:
        print("[A5/8] world.stop 收尾...", flush=True)
        world.stop()

    outcome = result.outcomes[0]
    episode_id = outcome.episode_id
    assert outcome.steps >= 1, f"阶段 A outcome.steps 应为正，实为 {outcome.steps}"

    run_dir = TRACE_ROOT / run_id
    anchor = json.loads((run_dir / "checkpoints" / "run.json").read_text(encoding="utf-8"))
    cursor = anchor["last_event_id"]

    step_dir = run_dir / "checkpoints" / "step" / safe(episode_id)
    saved_steps = sorted(int(p.stem) for p in step_dir.glob("*.json"))
    assert saved_steps, f"阶段 A 没有留下任何 step 存档：{step_dir}"
    restore_step = saved_steps[-1]
    print(
        f"[A6/8] 阶段 A 完成：episode={episode_id} steps={outcome.steps} "
        f"存档步={saved_steps} 游标={cursor}",
        flush=True,
    )

    # ---- 阶段 B：模拟崩溃后重启，从最后一个存档步恢复 ----
    print(f"[B1/8] 重新 build_real（resume_cursor={cursor}，模拟崩溃后新进程）...", flush=True)
    data_center2, reviewer2 = make_review_pair()
    harness2, _trace2, world2, _tools2 = build_real(
        ROM,
        STATE,
        run_id=run_id,
        resume_cursor=cursor,
        reviewer=reviewer2,
        data_center=data_center2,
        auto_push_goals=False,
        auto_decide_done=False,
    )
    print("[B2/8] build_real 完成。", flush=True)
    try:
        print(f"[B3/8] resume_run(run, {episode_id}, step={restore_step}) 开始...", flush=True)
        result2 = harness2.resume_run(run_id, episode_id, restore_step)
        print("[B4/8] resume_run 完成。", flush=True)
    finally:
        print("[B5/8] world.stop 收尾...", flush=True)
        world2.stop()

    outcome2 = result2.outcomes[0]
    assert outcome2.steps >= 1, f"恢复后 outcome.steps 应为正，实为 {outcome2.steps}"
    assert outcome2.reason, "恢复后 outcome.reason 不应为空"

    # ---- 判定 2：checkpoint_restore 事件存在且 restored_step 对得上 ----
    events: list[dict] = []
    for name in (f"{run_id}.jsonl", f"{safe(episode_id)}.jsonl"):
        path = run_dir / "episodes" / name
        assert path.is_file(), f"缺 trace 文件：{path}"
        events += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    restores = [e for e in events if e.get("payload", {}).get("kind") == "checkpoint_restore"]
    assert restores, "恢复后 trace 里没有任何 checkpoint_restore 事件"
    assert any(
        e["payload"].get("restored_step") == restore_step
        and e["payload"].get("restored_episode_id") == episode_id
        for e in restores
    ), f"checkpoint_restore 的 restored 三元组不对：{[e['payload'] for e in restores]}"

    # ---- 判定 3：event_id 全局排序严格连续（废弃段截掉后从游标 +1 无缝续写）----
    ids = sorted(e["event_id"] for e in events)
    assert len(set(ids)) == len(ids), f"恢复后 event_id 有重号：{ids}"
    assert ids == list(range(ids[0], ids[0] + len(ids))), f"恢复后 event_id 有缺号：{ids}"
    assert ids[-1] > cursor, f"恢复后没有新事件写入（最大 id {ids[-1]} ≤ 游标 {cursor}）"

    # ---- 判定 4：voided 归档目录真实生成 ----
    voided = sorted((run_dir / "checkpoints").glob("voided-*"))
    assert voided, "恢复后没有任何 voided-* 归档目录——废弃时间线处理没发生"

    write_last_run(run_id, episode_id)
    print(
        f"PASS  restore: 自 step {restore_step} 恢复，游标 {cursor} 后续写 {len(events)} 条连续，"
        f"归档 {len(voided)} 个 voided，steps={outcome2.steps} reason={outcome2.reason!r}"
    )


if __name__ == "__main__":
    main()
