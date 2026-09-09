"""维度 2（trace）：run 级 + 全部 episode 级事件按 event_id 全局排序后严格连续。

两类事件文件各自内部有序，但交叉分配 id（dispatch 期间的 id 落进 episode
文件、前后落进 run 文件）——必须按 event_id 全局排序后才能判断"是不是真的
严格递增、没有缺号/重号"，不能直接按文件读取顺序比。

**一个 run 可能有不止一个 episode**（reflect() 判定失败且预算未耗尽会直接
retry 出下一个 episode——resume 之后重新走一次判定，模型给出跟阶段 A 不同
的结论完全正常）。`resolve_run()` 只按 mtime 挑一个"最新"的 episode 文件，
是给维度 3/4（查单个 episode 自己的存档/记忆是否自洽）用的定位——这里如果
照抄只读那一个 episode 文件，其余 episode 的事件会被整段漏掉，被误判成
"event_id 缺号"（实测踩过：真实数据是 `run(0,1,122) + ep1(2..60) +
ep2(61..121)`，两个 episode 首尾相接，只挑 ep2 会看起来缺 2..60）。这里改
成读该 run_id 下**全部** `<run_id>-ep*.jsonl`——run 级骨架/model_call 的判定
本来就只看事件种类，不关心具体落在哪个 episode。

要求：
  1. 排序后 event_id 严格连续（无缺号、无重号）；
  2. payload.kind 同时出现 run_start / run_end / episode_start / episode_end；
  3. 至少一条 type=model_call（证明真的调了模型，不是空跑）。

前置条件：先跑 `check_harness` 生成 trace 产物。
"""

from __future__ import annotations

import json

from pokemon_agent.experiment.real_check.common import TRACE_ROOT, resolve_run


def _load_events(run_id: str) -> list[dict]:
    """读 run 级文件 + 该 run 下全部 episode 级文件（不止 resolve_run() 选中的那个——
    见模块 docstring）。"""
    episodes_dir = TRACE_ROOT / run_id / "episodes"
    run_file = episodes_dir / f"{run_id}.jsonl"
    assert run_file.is_file(), f"缺文件：{run_file}"
    paths = [run_file] + sorted(episodes_dir.glob(f"{run_id}-ep*.jsonl"))
    assert len(paths) > 1, f"{episodes_dir} 下一个 episode 级文件都没有"

    events: list[dict] = []
    for path in paths:
        events += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return events


def main() -> None:
    meta = resolve_run()
    run_id = meta["run_id"]

    events = _load_events(run_id)
    events.sort(key=lambda e: e["event_id"])
    ids = [e["event_id"] for e in events]

    assert len(set(ids)) == len(ids), f"event_id 有重号：{ids}"
    assert ids == list(range(ids[0], ids[0] + len(ids))), f"event_id 有缺号：{ids}"

    kinds = {e.get("payload", {}).get("kind", "") for e in events}
    assert {"run_start", "run_end"} <= kinds, f"缺 run 级骨架事件，实有：{kinds}"
    assert {"episode_start", "episode_end"} <= kinds, f"缺 episode 级骨架事件，实有：{kinds}"

    model_calls = [e for e in events if e.get("type") == "model_call"]
    assert model_calls, "没有任何 model_call 事件——模型没被真实调用到"

    print(
        f"PASS  trace: {len(events)} 条事件、event_id [{ids[0]}..{ids[-1]}] 连续无缺号无重号，"
        f"骨架 kind 齐全，model_call {len(model_calls)} 条"
    )


if __name__ == "__main__":
    main()
