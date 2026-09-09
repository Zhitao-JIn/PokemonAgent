"""维度 4（memory）：StepMemory / ObjectMemory 落盘自洽。

`steps-<episode_id>.jsonl`（StepMemory）与 `ep-<episode_id>.jsonl`（ObjectMemory）
这两个文件**不存在是正常的**：episode 成功收尾后 StepMemory 会被蒸馏链清空
（`discard_episode_steps`），本局任务（3 步短目标）大概率也不触发物体交互。
但如果文件存在，就**不能是空文件**——那是"写了一半/被清了一半"的中间态。

前置条件：先跑 `check_harness` 生成记忆产物。
"""

from __future__ import annotations

import pathlib

from pokemon_agent.experiment.real_check.common import (
    OBJECT_EVENTS_DIR,
    STEP_MEMORY_DIR,
    resolve_run,
    safe,
)


def _check(path: pathlib.Path, label: str) -> None:
    if path.is_file():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, f"{label} 文件存在但是空的——不该出现的中间态：{path}"
        print(f"  {label}: 存在且非空（{len(lines)} 行）")
    else:
        print(f"  {label}: 不存在（正常——蒸馏链清空 / 未触发物体交互）")


def main() -> None:
    meta = resolve_run()
    episode_id = meta["episode_id"]

    _check(STEP_MEMORY_DIR / f"steps-{safe(episode_id)}.jsonl", "StepMemory")
    _check(OBJECT_EVENTS_DIR / f"ep-{safe(episode_id)}.jsonl", "ObjectMemory")
    print("PASS  memory: StepMemory / ObjectMemory 落盘状态自洽")


if __name__ == "__main__":
    main()
