"""维度 2（trace）：盘上全量事件连续，废弃分支 = 一个 valid=false 的连续块。

0910 起落盘为一条事件一个 `trace_data/<run_id>/events/<run_id>-<event_id>.json`
（见 `PLAN_memory_trace_layout.md` §6）——不再有"按局一个 jsonl"的中间粒度，
也不再有 run/episode 两类文件交叉分配 id 的问题：直接扫全部事件文件、按
解析出的 `event_id` 排序即可（**文件名只是人肉看的辅助**，排序永远以内容为准）。
checkpoint resume 会把废弃分支的事件原地打 `valid=false`（不删）；event_id
永远单调递增、恢复续跑不重用旧号——所以**盘上全量事件**（含 invalid）才是
连续的，有效时间线在废弃块处留洞是设计行为，不是缺号。

要求：
  1. 全量事件（含 valid=false）按 event_id 严格连续（无缺号、无重号）；
  2. valid=false 的事件构成一个连续块（void_after 只打 id > 游标的一段，
     恢复后写新号不重用——洞只能是中间一块，不能散落）；
  3. 有效事件（valid=true）的 payload.kind 同时出现 run_start / run_end /
     episode_start / episode_end；
  4. 至少一条 type=model_call（证明真的调了模型，不是空跑）。

前置条件：先跑 `check_harness` 生成 trace 产物。
"""

from __future__ import annotations

import json

from experiment.real_check.common import TRACE_ROOT, resolve_run


def _load_events(run_id: str) -> list[dict]:
    """读该 run 下全部事件文件（含 valid=false，残文件跳过）。"""
    events_dir = TRACE_ROOT / run_id / "events"
    assert events_dir.is_dir(), f"缺目录：{events_dir}"
    paths = sorted(events_dir.glob("*.json"))
    assert paths, f"{events_dir} 下一个事件文件都没有"

    events: list[dict] = []
    for path in paths:
        if path.name.endswith(".tmp"):
            continue
        try:
            events.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return events


def main() -> None:
    meta = resolve_run()
    run_id = meta["run_id"]

    events = _load_events(run_id)
    events.sort(key=lambda e: e["event_id"])
    ids = [e["event_id"] for e in events]

    # 步骤 1：盘上全量连续——event_id 从首号起一格不缺，废弃块也在盘上。
    assert len(set(ids)) == len(ids), f"event_id 有重号：{ids}"
    assert ids == list(range(ids[0], ids[0] + len(ids))), f"event_id 有缺号：{ids}"

    # 步骤 2：废弃块形状——valid=false 的 id 必须是中间一段连续区间，
    # 不能在有效时间线之前或之后（resume 从未重用旧号，洞只能在中间）。
    voided = [e["event_id"] for e in events if not e.get("valid", True)]
    if voided:
        lo, hi = min(voided), max(voided)
        assert voided == list(range(lo, hi + 1)), f"valid=false 不连续：{voided}"
        assert lo > ids[0] and hi < ids[-1], f"废弃块贴边（应为中间一块）：[{lo}..{hi}]"

    valid = [e for e in events if e.get("valid", True)]
    kinds = {e.get("payload", {}).get("kind", "") for e in valid}
    assert {"run_start", "run_end"} <= kinds, f"缺 run 级骨架事件，实有：{kinds}"
    assert {"episode_start", "episode_end"} <= kinds, f"缺 episode 级骨架事件，实有：{kinds}"

    model_calls = [e for e in valid if e.get("type") == "model_call"]
    assert model_calls, "没有任何 model_call 事件——模型没被真实调用到"

    void_note = (
        f"，废弃块 [{min(voided)}..{max(voided)}] {len(voided)} 条 valid=false" if voided else ""
    )
    print(
        f"PASS  trace: {len(valid)} 条有效事件、盘上全量 [{ids[0]}..{ids[-1]}] "
        f"连续无缺号无重号{void_note}，骨架 kind 齐全，model_call {len(model_calls)} 条"
    )


if __name__ == "__main__":
    main()
