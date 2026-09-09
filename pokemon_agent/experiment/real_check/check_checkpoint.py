"""维度 3（checkpoint）：step 存档的 state/json 文件名集合完全一致，且带 run 级快照。

`checkpoints/step/<episode_id>/` 下每份 step 存档由一对 `<step>.state`（模拟器
世界快照）+ `<step>.json`（EpisodeRunState + RunState 双重 dump，提交点）构成
——没有单独的 run 级文件（0909 CHANGELOG：run.json 合并进 step 存档）。要求
两者的文件名（不含后缀）集合完全一致——不成对说明存档写坏了，
`CheckpointTool.load()` 恢复时会直接拒绝；json 里还要能读出 `run_state_dump`，
证明 run 级信息确实一起打包进来了，不是漏传。

前置条件：先跑 `check_harness` 生成 checkpoint 产物。
"""

from __future__ import annotations

import json

from pokemon_agent.experiment.real_check.common import TRACE_ROOT, resolve_run, safe


def main() -> None:
    meta = resolve_run()
    run_id, episode_id = meta["run_id"], meta["episode_id"]

    cp_dir = TRACE_ROOT / run_id / "checkpoints"
    step_dir = cp_dir / "step" / safe(episode_id)
    assert step_dir.is_dir(), f"没有 step 存档目录：{step_dir}"
    state_steps = {p.stem for p in step_dir.glob("*.state")}
    json_steps = {p.stem for p in step_dir.glob("*.json")}
    assert state_steps, "一个 step 存档都没有"
    assert state_steps == json_steps, (
        f"state/json 不成对：state 有 {sorted(state_steps)}，json 有 {sorted(json_steps)}"
    )

    # 抽一份（最大 step 那份）核对 run_state_dump 确实打包进来了。
    latest_step = max(int(s) for s in state_steps)
    meta_json = json.loads((step_dir / f"{latest_step}.json").read_text(encoding="utf-8"))
    assert "run_state_dump" in meta_json and meta_json["run_state_dump"], (
        f"{latest_step}.json 里没有 run_state_dump：run 级快照没有一起打包进来"
    )
    assert meta_json["run_state_dump"].get("run_id") == run_id, (
        "run_state_dump.run_id 跟当前 run_id 对不上"
    )

    print(
        f"PASS  checkpoint: step 存档 {sorted(state_steps)} 的 state/json 成对，"
        f"且带 run_state_dump（run_id 核对通过）"
    )


if __name__ == "__main__":
    main()
