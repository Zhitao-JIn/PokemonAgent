"""维度 2（trace）：run 级 + episode 级事件按 event_id 全局排序后严格连续。

两个事件文件各自内部有序，但交叉分配 id（dispatch 期间的 id 落进 episode
文件、前后落进 run 文件）——必须按 event_id 全局排序后才能判断"是不是真的
严格递增、没有缺号/重号"，不能直接按文件读取顺序比。

要求：
  1. 排序后 event_id 严格连续（无缺号、无重号）；
  2. payload.kind 同时出现 run_start / run_end / episode_start / episode_end；
  3. 至少一条 type=model_call（证明真的调了模型，不是空跑）。

前置条件：先跑 `check_harness` 生成 trace 产物。
"""

from __future__ import annotations

import json

from pokemon_agent.experiment.real_check.common import TRACE_ROOT, resolve_run, safe


def _load_events(run_id: str, episode_id: str) -> list[dict]:
    episodes_dir = TRACE_ROOT / run_id / "episodes"
    events: list[dict] = []
    for name in (f"{run_id}.jsonl", f"{safe(episode_id)}.jsonl"):
        path = episodes_dir / name
        assert path.is_file(), f"缺文件：{path}"
        events += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return events


def main() -> None:
    meta = resolve_run()
    run_id, episode_id = meta["run_id"], meta["episode_id"]

    events = _load_events(run_id, episode_id)
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
