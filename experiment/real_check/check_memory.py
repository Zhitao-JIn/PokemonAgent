"""维度 4（memory）：StepMemory / ObjectMemory 落盘自洽。

0910 起落盘为一条记录一个文件：`memory/<kind>/<uuid>.json`（见
`PLAN_memory_trace_layout.md` §2/§4.1），run_id / episode_id / step 都是记录
metadata 里的普通字段——按 episode_id 过滤要扫 metadata，不能靠文件名。

`step_memory/` 下累积着历次 run 的全部单步记忆：**局正常收尾不碰记忆**
（0910 拍板——step 记忆按 `episode_id` 查询天然隔离，不需要清场），只有
checkpoint 恢复才会把游标之后的分支归档走。所以"这一局的记录不存在"说明这一局
一步都没写完就崩了；如果存在，就**不能是空文件**——那是"写了一半"的中间态。
`object_memory/` 同理（本局任务大概率不触发物体交互，不存在也正常）。

前置条件：先跑 `check_harness` 生成记忆产物。
"""

from __future__ import annotations

import json
import pathlib

from experiment.real_check.common import MEMORY_ROOT, resolve_run


def _check(kind_dir: pathlib.Path, episode_id: str, label: str) -> None:
    if not kind_dir.is_dir():
        print(f"  {label}: 目录不存在（{kind_dir}）——该类记忆从未写入过，正常")
        return
    hits = 0
    for path in sorted(kind_dir.glob("*.json")):
        if path.name.endswith(".tmp") or path.name == "index.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise AssertionError(
                f"{label} 存在残文件（半个 JSON，写穿不该留这种东西）：{path}"
            ) from None
        if raw.get("metadata", {}).get("episode_id") == episode_id:
            hits += 1
    if hits:
        print(f"  {label}: 本局有 {hits} 条记录，全部非空、可解析")
    else:
        print(f"  {label}: 本局无记录（正常——蒸馏链收尾 / 未触发物体交互）")


def main() -> None:
    meta = resolve_run()
    episode_id = meta["episode_id"]

    _check(MEMORY_ROOT / "step_memory", episode_id, "StepMemory")
    _check(MEMORY_ROOT / "object_memory", episode_id, "ObjectMemory")
    print("PASS  memory: StepMemory / ObjectMemory 落盘状态自洽")


if __name__ == "__main__":
    main()
