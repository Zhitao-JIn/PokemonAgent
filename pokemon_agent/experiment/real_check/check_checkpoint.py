"""维度 3（checkpoint）：run 锚点存在，step 存档的 state/json 文件名集合完全一致。

`checkpoints/run.json` 是 run 级锚点；`checkpoints/step/<episode_id>/` 下每份
step 存档由一对 `<step>.state`（模拟器世界快照）+ `<step>.json`（提交点）构成。
要求两者的文件名（不含后缀）集合完全一致——不成对说明存档写坏了，
`CheckpointTool.load()` 恢复时会直接拒绝。

前置条件：先跑 `check_harness` 生成 checkpoint 产物。
"""

from __future__ import annotations

from pokemon_agent.experiment.real_check.common import TRACE_ROOT, resolve_run, safe


def main() -> None:
    meta = resolve_run()
    run_id, episode_id = meta["run_id"], meta["episode_id"]

    cp_dir = TRACE_ROOT / run_id / "checkpoints"
    assert (cp_dir / "run.json").is_file(), f"run.json 缺失：{cp_dir / 'run.json'}"

    step_dir = cp_dir / "step" / safe(episode_id)
    assert step_dir.is_dir(), f"没有 step 存档目录：{step_dir}"
    state_steps = {p.stem for p in step_dir.glob("*.state")}
    json_steps = {p.stem for p in step_dir.glob("*.json")}
    assert state_steps, "一个 step 存档都没有"
    assert state_steps == json_steps, (
        f"state/json 不成对：state 有 {sorted(state_steps)}，json 有 {sorted(json_steps)}"
    )

    print(f"PASS  checkpoint: run.json 存在，step 存档 {sorted(state_steps)} 的 state/json 成对")


if __name__ == "__main__":
    main()
