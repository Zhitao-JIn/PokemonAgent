"""裸事件 → `ObjectFactEvent`：**补三章 + 落库形状组装**（P6 瘦身后）。

**判定已前移 world**（P6 定案）：「这一步碰到了什么」（候选格 / 姿势 / outcome /
object_kind）由 `world/object_events.py::judge_press` 在 server 侧判定——逐键
路径随 `step` 响应带 `event`、脚本路径随终态报告带 `events[]`，两条路径产出
**同一个 dict 形状**。本文件只做 harness 侧剩下的事：

- **补三章**：`episode_id` / `step`（哪一局、哪一步——大脑/harness 的坐标，
  world 不知道）；`run_id` 由调用方（落库节点）盖；
- **组装**：裸 dict 按 outcome 分族成 `ObjectDialogEvent` / `ObjectWarpEvent` /
  `ObjectStillEvent`（落库与放记忆的三种类型，字段见 `schemas.memory`）。

**两路径在 `store_object_semantic_memory` 节点汇合**：先取本步的裸事件
（脚本动作取报告 `events[]` 批量、按键动作取 step 响应单条），再交这里统一
补章，最后经 `memorize(kind=object)` 落库——「两路径逐字段一致」由
`tests/test_p6_event_alignment.py` 的钉子测试守住。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
)


def stamp_events(
    raw_events: list[dict[str, Any]], episode_id: str, step: int
) -> list[ObjectFactEvent]:
    """给裸事件补 `episode_id` / `step` 两章，按 outcome 组装成落库类型。

    前置条件：`raw_events` 是 `world/object_events.py` 判定产出的 dict
        （两路径同形——step 响应的 `event` 与脚本报告的 `events[]` 元素）。
    后置条件：返回的事件按 `place` 唯一（判定层保证）；列表可为空。
    """
    events: list[ObjectFactEvent] = []
    for raw in raw_events:
        common = {
            "episode_id": episode_id,
            "step": step,
            "actor_place": raw["actor_place"],
            "place": raw["place"],
            "object_kind": raw["object_kind"],
            "button": raw["button"],
        }
        outcome = raw["outcome"]
        if outcome == "dialog":
            events.append(ObjectDialogEvent(**common, text=raw["text"]))
        elif outcome == "warp":
            events.append(ObjectWarpEvent(**common, map_id=raw["map_id"]))
        else:
            events.append(ObjectStillEvent(**common))
    return events


__all__ = ["stamp_events"]
