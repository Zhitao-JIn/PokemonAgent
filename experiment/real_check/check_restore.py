"""维度 5（restore）：真实跨进程 checkpoint 恢复——load → void_after → 续跑。

前面的维度都只查"落盘产物长什么样"，没有任何脚本真正走过**读回路径**。
本脚本补上恢复链路的真实执行：

  阶段 A  build_real 完整跑一个 3 步 run（生成 trace / checkpoint / 记忆产物）；
  阶段 B  模拟"崩溃后重启"：读最后一步 checkpoint 拿事件游标（0909 起 run.json
          已合并进 step 存档，见 CHANGELOG）→ 带 `resume_cursor` 重新
          build_real（新进程语义：trace 从游标 +1 续写）→
          `resume_run(run_id, episode_id, step)` 走
          取存档 → 废弃时间线归档 → 世界快照回载 → 状态重建 → 续跑到收尾。

通过判定（全部独立可判）：
  1. 阶段 B 返回 run 级结算四元组；
  2. 恢复后 trace 里出现 `checkpoint_restore` 事件且 `restored_step` 对得上；
  3. 恢复后**有效**事件（valid=true）按 event_id 排序无重号：主前缀
     [0..cursor] 连续、游标之后的新事件从某个 >cursor 的号起连续——中间的
     缺号正是被废弃的分支（它们还留在盘上、只是 valid=false，这是 0910 起
     "trace 不删、打标"语义的预期形状）；
  4. `voided-*/` 归档目录真实生成（废弃时间线处理真的发生了）；
  5. 记忆侧跟着一起作废、且不留重号：
     a. 废弃时间线写下的 step 记忆不留重号——`(episode_id, step)` 至多一条；
     b. 废弃时间线写下的**局摘要**必须已被归档——恢复前该局摘要的 uuid 集合与
        恢复后无交集，且恢复后同一 `episode_id` 至多一条（两条并存会让
        `query_episode_summaries` 按 run_id 等值筛时同时返回两份互相矛盾的账）；
     c. 记忆侧确实动过手：`memory/voided-*/` 有新增。

**恢复哪一步由 `--step` 决定**（不给则取最后一个存档步，即原先的唯一口径）。
末步恢复也会归档该局的**局摘要**——局收尾（verify → write_episode）发生在最后
一个 checkpoint 之后、且自己没有 checkpoint，所以任何恢复点都会把那次收尾圈进
废弃窗口。`--step 1`（中间步）才可能额外压到 step 记忆的归档路径，前提是阶段 A
在恢复步真的执行过动作——本脚本的 GOAL 一步即达成时压不到，此时 (a) 是真空过。

跑完后把 last-run 指针指向恢复后的时间线，维度 2/3/4 可以直接对它复核。
前置条件：`ARK_API_KEY` 与 `DASHSCOPE_API_KEY` 都要有。
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import time

# native 层崩溃兜底：PyBoy/SDL/显卡驱动线程无声杀进程时，Python 来不及
# 留话——打开后崩溃点会 dump 各线程调用栈。
#
# 不再挂 dump_traceback_later 的周期性栈打印：4 分钟这个阈值比一次正常的
# 决策模型调用（重试预算 90s×3 次 + 退避，最坏能到 4 分半）短，健康跑也会
# 假警报，反而掩盖了真正卡死的信号——是不是真卡死，看进程还在不在动
# （有没有新的 [n/8] 打印）就够了，不需要栈探针。
faulthandler.enable()


def _episode_summary_uuids(episode_id: str) -> set[str]:
    """`memory/episode_memory/` 里该局摘要的 uuid 集合。

    走记录文件而不是索引：`index.json` 只是派生物，判定"摘要还在不在检索世界里"
    要的是真相层。md 类记录的正文是 frontmatter 里那段 JSON（`{uuid, metadata,
    payload}`），`---` 之后才是给检索用的 text。
    """
    from experiment.real_check.common import MEMORY_ROOT

    found: set[str] = set()
    for path in (MEMORY_ROOT / "episode_memory").glob("*.md"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8").split("---", 2)[1])
        except (IndexError, json.JSONDecodeError):
            continue
        if (meta.get("metadata") or {}).get("episode_id") == episode_id:
            found.add(str(meta.get("uuid") or path.stem))
    return found


def main() -> None:
    from experiment.real_check.common import (
        CHECKPOINT_ROOT,
        GOAL,
        MEMORY_ROOT,
        REVIEW_TIMEOUT,
        ROM,
        STATE,
        STEPS,
        SUCCESS_CRITERIA,
        TRACE_ROOT,
        make_review_pair,
        safe,
        write_last_run,
    )
    from pokemon_agent.build import build_real
    from pokemon_agent.schemas.brain import TaskForBrain

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="恢复到该局第几步开局；不给则取最后一个存档步",
    )
    args = parser.parse_args()

    run_id = f"restorecheck-{time.strftime('%m%d-%H%M%S')}"
    task = TaskForBrain(
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
        vision_model="qwen3.8-max",
        text_model="qwen-plus",
        max_tokens=25600,
        run_id=run_id,
        reviewer=reviewer,
        data_center=data_center,
        auto_push_goals=False,
        auto_decide_done=False,
    )
    print(f"[A2/8] build_real 完成（review 超时 {REVIEW_TIMEOUT:.0f}s）。", flush=True)
    try:
        print("[A3/8] harness.run 开始（3 步短目标）...", flush=True)
        outcomes, _total, _succeeded, _rate = harness.run(run_id=run_id, goals=[task])
        print("[A4/8] harness.run 完成。", flush=True)
    finally:
        print("[A5/8] world.stop 收尾...", flush=True)
        world.stop()
        print("[A5/8] world.stop 完成。", flush=True)

    outcome = outcomes[0]
    episode_id = outcome.episode_id
    assert outcome.steps >= 1, f"阶段 A outcome.steps 应为正，实为 {outcome.steps}"
    assert outcome.reason, "阶段 A outcome.reason 不应为空"

    run_dir = TRACE_ROOT / run_id
    cp_dir = CHECKPOINT_ROOT / run_id
    step_dir = cp_dir / "step" / safe(episode_id)
    saved_steps = sorted(int(p.stem) for p in step_dir.glob("*.json"))
    assert saved_steps, f"阶段 A 没有留下任何 step 存档：{step_dir}"
    restore_step = saved_steps[-1] if args.step is None else args.step
    if restore_step not in saved_steps:
        raise SystemExit(f"--step {restore_step} 没有存档；本局可选 {saved_steps}")
    # 记忆侧的两个快照：判定 5 要用它们区分"本次确实新增了归档"与"只有历史遗留"。
    # 摘要 uuid 走 <uuid>.md 的文件名（真相层），不读索引。
    memory_voided_before = {p.name for p in MEMORY_ROOT.glob("voided-*")}
    summaries_before = _episode_summary_uuids(episode_id)

    # 游标从"要恢复到的那一步"自己的 checkpoint 里读——0909 起 run.json 已经
    # 合并进 step 存档（不再有单独的 run 级文件），一份 json 里游标跟
    # run_state_dump/state_dump 天然一致。
    anchor = json.loads((step_dir / f"{restore_step}.json").read_text(encoding="utf-8"))
    cursor = anchor["last_event_id"]
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
        vision_model="qwen3.8-max",
        text_model="qwen-plus",
        max_tokens=25600,
        run_id=run_id,
        resume_cursor=cursor,
        reviewer=reviewer2,
        data_center=data_center2,
        auto_push_goals=False,
        auto_decide_done=False,
    )
    print(f"[B2/8] build_real 完成（review 超时 {REVIEW_TIMEOUT:.0f}s）。", flush=True)
    try:
        print(f"[B3/8] resume_run(run, {episode_id}, step={restore_step}) 开始...", flush=True)
        outcomes2, _t2, _s2, _r2 = harness2.resume_run(run_id, episode_id, restore_step)
        print("[B4/8] resume_run 完成。", flush=True)
    finally:
        print("[B5/8] world.stop 收尾...", flush=True)
        world2.stop()
        print("[B5/8] world.stop 完成。", flush=True)

    outcome2 = outcomes2[0]
    assert outcome2.steps >= 1, f"恢复后 outcome.steps 应为正，实为 {outcome2.steps}"
    assert outcome2.reason, "恢复后 outcome.reason 不应为空"

    # ---- 判定 2：checkpoint_restore 事件存在且 restored_step 对得上 ----
    # 读该 run 的**全部**事件文件（0910 起一条事件一个
    # `events/<run_id>-<event_id>.json`）——resume 完之后 reflect() 可能判定
    # 失败且预算未耗尽，直接 retry 出下一个 episode，漏读任一文件都会让
    # 判定 3 的连续性检查凭空出现缺号。
    events_dir = run_dir / "events"
    events: list[dict] = []
    for path in sorted(events_dir.glob(f"{run_id}-*.json")):
        if path.name.endswith(".tmp"):
            continue
        assert path.is_file(), f"缺 trace 文件：{path}"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if raw.get("valid", True):
            events.append(raw)
    assert events, f"{events_dir} 下没有任何有效事件"
    restores = [e for e in events if e.get("payload", {}).get("kind") == "checkpoint_restore"]
    assert restores, "恢复后 trace 里没有任何 checkpoint_restore 事件"
    # `trace_render.checkpoint_restore()` 把 payload 里的数值字段（`restored_step`/
    # `cursor`）渲染成字符串（跟本文件其余 render 函数同一惯例，比如 verdict 的
    # `done`/`pushed_count`）——payload 是给日志/回放读的文本，不是类型化数据，
    # 这里比对要按字符串比，不能拿 int 直接 `==`。
    assert any(
        e["payload"].get("restored_step") == str(restore_step)
        and e["payload"].get("restored_episode_id") == episode_id
        for e in restores
    ), f"checkpoint_restore 的 restored 三元组不对：{[e['payload'] for e in restores]}"

    # ---- 判定 3：有效时间线（valid=true）event_id 无重号，主前缀连续、
    # resume 之后连续——中间的缺号 = 被废弃的分支（盘上还在，只是 valid=false，
    # 0910 起"trace 不删、打标"语义的预期形状）。
    ids = sorted(e["event_id"] for e in events)
    assert len(set(ids)) == len(ids), f"恢复后有效 event_id 有重号：{ids}"
    assert set(range(0, cursor + 1)) <= set(ids), (
        f"主前缀 [0..{cursor}] 有缺号：{ids[: cursor + 1]}"
    )
    post = [i for i in ids if i > cursor]
    assert post, f"恢复后没有新事件写入（全部有效 id 都 ≤ 游标 {cursor}）"
    assert post == list(range(post[0], post[0] + len(post))), f"resume 后的续写有缺号：{post}"

    # ---- 判定 4：废弃处理真实发生 ----
    # checkpoint 侧：废弃局的 step 归档；memory 侧：作废记录归档
    # （memory/voided-<ts>/，由 MemoryTool 生成）。
    voided = sorted(cp_dir.glob("voided-*"))
    assert voided, "恢复后没有任何 voided-* 归档目录——废弃时间线处理没发生"

    # ---- 判定 5：记忆侧跟着一起作废，且不留重号 ----
    # 恢复步 N 是"第 N 步开局"（`RunHarness.resume_run` docstring）：checkpoint N
    # 时刻已完成的是 step 0..N-1，废弃分支写下的 step N..M 全部要归档，重跑才能
    # 从 step N 干净地重新写。归档口径是 checkpoint 工具传给 MemoryTool 的
    # `keep_step`——`_step_within` 判 `step <= keep_step` 保留，所以 keep_step
    # 必须取「恢复步 - 1」（`step=0` 落到哨兵 -1 = 整局废弃）。
    memory_voided_after = {p.name for p in MEMORY_ROOT.glob("voided-*")}
    new_voided = memory_voided_after - memory_voided_before

    # 判定 5b：该局的**局摘要**必须已被作废。局收尾（verify → write_episode）在
    # 该局最后一个 checkpoint 之后、且没有自己的 checkpoint，所以任何恢复点都
    # 把那次收尾圈进废弃窗口。摘要不跟着归档的话，重跑会落下第二条同
    # episode_id 的记录，`query_episode_summaries`（按 run_id 等值筛）会把两份
    # 互相矛盾的账一起喂给大脑。
    summaries_after = _episode_summary_uuids(episode_id)
    assert not (summaries_before & summaries_after), (
        f"该局恢复前的摘要仍在检索世界里：{sorted(summaries_before & summaries_after)}——"
        "void_memory_after 漏了 episode_memory 这一类"
    )
    assert len(summaries_after) <= 1, (
        f"同一 episode_id 有多条局摘要：{sorted(summaries_after)}——"
        "废弃时间线那条没被归档，重跑又写了一条"
    )

    if summaries_before or restore_step < saved_steps[-1]:
        assert new_voided, (
            f"自 step {restore_step} 恢复（该局恢复前摘要 {len(summaries_before)} 条、"
            f"该局存档步 {saved_steps}），但 memory/voided-*/ 一个都没新增——"
            "记忆侧作废没有发生"
        )

    seen: dict[tuple[str, int], int] = {}
    for path in (MEMORY_ROOT / "step_memory").glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payload = raw.get("payload") or {}
        if "step" not in payload:
            continue
        key = ((raw.get("metadata") or {}).get("episode_id", ""), int(payload["step"]))
        seen[key] = seen.get(key, 0) + 1
    duplicates = sorted(k for k, n in seen.items() if n > 1)
    assert not duplicates, (
        f"同一局同一步存在多条 step 记忆（恢复步={restore_step}）：{duplicates}——"
        "checkpoint_tool.void_after 给 MemoryTool 的 keep_step 取错了（该取恢复步 - 1），"
        "废弃分支那条 step N 记录落在保留区里漏网，重跑又写一条新记录"
    )

    write_last_run(run_id, episode_id)
    print(
        f"PASS  restore: 自 step {restore_step} 恢复，游标 {cursor} 后续写 {len(events)} 条连续，"
        f"归档 {len(voided)} 个 voided，记忆侧新增 {len(new_voided)} 个归档目录"
        f"（含该局摘要 {len(summaries_before - summaries_after)} 条），"
        f"step 记忆 {len(seen)} 条无重号、该局摘要 {len(summaries_after)} 条，"
        f"steps={outcome2.steps} reason={outcome2.reason!r}"
    )


if __name__ == "__main__":
    main()
