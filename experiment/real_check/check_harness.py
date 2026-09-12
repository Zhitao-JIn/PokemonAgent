"""维度 1（harness）：build_real 装配真实链路，跑 3 步短目标。

要求：`begin → plan → dispatch → ... → run_end` 整张图跑到底不崩、返回
run 级结算四元组。这是四个核对里唯一真正驱动 PyBoy + 真实 Brain 的
脚本——"硬崩溃/重启"如果出在这一步，看打印停在哪一行
就能定位是 build_real（PyBoy 初始化）、harness.run（图 + 真实模型调用）、
还是 world.stop（模拟器收尾）。

前置条件：`ARK_API_KEY` 与 `DASHSCOPE_API_KEY` 两个环境变量都要有。
"""

from __future__ import annotations

import faulthandler
import time

# 同 check_restore：enable() 抓 native 崩溃，dump_traceback_later 抓卡死
# （每 4 分钟例行打印全线程栈，健康跑完会有 1-2 次噪音）。
faulthandler.enable()
faulthandler.dump_traceback_later(timeout=240, repeat=True)


def main() -> None:
    from experiment.real_check.common import (
        GOAL,
        REVIEW_TIMEOUT,
        ROM,
        STATE,
        STEPS,
        SUCCESS_CRITERIA,
        make_review_pair,
        write_last_run,
    )
    from pokemon_agent.brain import Task
    from pokemon_agent.build import build_real

    run_id = f"realcheck-{time.strftime('%m%d-%H%M%S')}"
    print(f"[1/6] build_real 装配中（run_id={run_id}）...", flush=True)
    # 两个开关全关：plan 跳过模型调用、不压栈不判 done；review 用
    # DataCenterReviewer（与 api.py 同构）——栈清空后交人工审查，核对脚本
    # 没有前端，等 REVIEW_TIMEOUT 秒没人答按 STOP 收场（有限任务确定性终止）。
    data_center, reviewer = make_review_pair()
    harness, trace, world, tools = build_real(
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
    print(f"[2/6] build_real 完成（review 超时 {REVIEW_TIMEOUT:.0f}s）。", flush=True)

    task = Task(
        task_id="realcheck",
        goal=GOAL,
        success_criteria=SUCCESS_CRITERIA,
        max_steps=STEPS,
    )

    try:
        print("[3/6] harness.run 开始（3 步短目标）...", flush=True)
        outcomes, _total, _succeeded, _rate = harness.run(run_id=run_id, goals=[task])
        print("[4/6] harness.run 完成。", flush=True)
    finally:
        print("[5/6] world.stop 收尾...", flush=True)
        world.stop()
        print("[6/6] world.stop 完成。", flush=True)

    outcome = outcomes[0]
    assert outcome.steps >= 1, f"outcome.steps 应为正，实为 {outcome.steps}"
    assert outcome.reason, "outcome.reason 不应为空"

    write_last_run(run_id, outcome.episode_id)
    print(
        f"PASS  harness: run={run_id} episode={outcome.episode_id} "
        f"steps={outcome.steps} reason={outcome.reason!r}"
    )


if __name__ == "__main__":
    main()
