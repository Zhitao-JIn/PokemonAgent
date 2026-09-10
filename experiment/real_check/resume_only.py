"""调试工具：跳过阶段 A（造一个全新的 3 步 run），直接对着磁盘上已有的
checkpoint 三元组 `(run_id, episode_id, step)` 发起 `resume_run()`。

不是维度 5 的替代——`check_restore.py` 走完整的"造 run → 模拟崩溃 → 恢复 →
四条判据"链路，是那次真实回归的准绳；这个脚本只干 `check_restore.py` 阶段
B 那一半，用来在排查 resume 之后的问题（比如某个节点卡住/变慢）时反复重跑，
不用每次都先陪跑一遍阶段 A（build_real 装配 + 3 步决策，几十秒到几分钟）。

定位规则：
  - 不给参数：`common.resolve_run()` 找最近一次 realcheck/restorecheck 产物，
    再取该 episode 下最大的已存档 step。
  - 可选 `--run-id` / `--episode-id` / `--step` 精确指定，覆盖自动定位。

跟 check_restore.py 阶段 B 完全同构：读该 step 自己的 checkpoint 拿游标 →
带 `resume_cursor` 重新 `build_real`（新进程语义）→ `resume_run()`。
不含任何 PASS/FAIL 断言——这是给人看着调的，不是回归判据。
"""

from __future__ import annotations

import argparse
import faulthandler
import json

faulthandler.enable()
faulthandler.dump_traceback_later(timeout=240, repeat=True)


def _latest_step(step_dir) -> int:
    saved = sorted(int(p.stem) for p in step_dir.glob("*.json"))
    if not saved:
        raise SystemExit(f"{step_dir} 下没有任何 step 存档")
    return saved[-1]


def main() -> None:
    from experiment.real_check.common import (
        CHECKPOINT_ROOT,
        ROM,
        STATE,
        make_review_pair,
        resolve_run,
        safe,
    )
    from pokemon_agent.build import build_real

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="不给则用 resolve_run() 自动定位")
    parser.add_argument("--episode-id", default=None, help="不给则用 resolve_run() 自动定位")
    parser.add_argument(
        "--step", type=int, default=None, help="不给则取该 episode 已存档的最大 step"
    )
    args = parser.parse_args()

    if args.run_id and args.episode_id:
        run_id, episode_id = args.run_id, args.episode_id
    else:
        located = resolve_run()
        run_id = args.run_id or located["run_id"]
        episode_id = args.episode_id or located["episode_id"]

    cp_dir = CHECKPOINT_ROOT / run_id
    step_dir = cp_dir / "step" / safe(episode_id)
    step = args.step if args.step is not None else _latest_step(step_dir)

    step_json = step_dir / f"{step}.json"
    assert step_json.is_file(), f"找不到 checkpoint：{step_json}"
    anchor = json.loads(step_json.read_text(encoding="utf-8"))
    cursor = anchor["last_event_id"]

    print(f"[1/4] 定位到 run={run_id} episode={episode_id} step={step} 游标={cursor}", flush=True)

    print(f"[2/4] build_real（resume_cursor={cursor}，模拟崩溃后新进程）...", flush=True)
    data_center, reviewer = make_review_pair()
    harness, _trace, world, _tools = build_real(
        ROM,
        STATE,
        vision_model="qwen3.8-max",
        text_model="qwen-plus",
        max_tokens=25600,
        run_id=run_id,
        resume_cursor=cursor,
        reviewer=reviewer,
        data_center=data_center,
        auto_push_goals=False,
        auto_decide_done=False,
    )
    print("[3/4] build_real 完成，resume_run 开始...", flush=True)
    try:
        outcomes, _total, _succeeded, _rate = harness.resume_run(run_id, episode_id, step)
        print(f"[4/4] resume_run 完成：outcomes={[o.model_dump() for o in outcomes]}")
    finally:
        print("world.stop 收尾...", flush=True)
        world.stop()
        print("world.stop 完成。", flush=True)


if __name__ == "__main__":
    main()
