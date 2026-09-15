"""object 交互事件的文字化：`known_objects` 段的组装辅助（纯函数，不查库）。

这是"数据结构 → 文字"的那一步，住在 prompts/ 是因为输出措辞本身是
`decide_action` prompt 契约的一部分（改措辞 = 改 prompt，要进版本归因）。
memory 只交出事件序列，这里负责把它们变成给模型读的行。

模板（每一行 = 一条事件，按 step 升序，行首带 episode 和 step——新旧由
行内自明，不做任何去重/拼接/裁剪/门特判）：

    ep1 step12 站在(2,4) 按 up → 地图39(2,3)的门：进入新地图42
    ep1 step15 站在(2,7) 按 a → 地图39(2,7)的人：对话"BLUE is out at GrandPa's lab."
    ep1 step18 站在(5,4) 按 up → 地图39(5,5)的门：无效果
"""

from __future__ import annotations

from collections.abc import Sequence

from pokemon_agent.schemas.memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
)


def render_object_events(events: Sequence[ObjectFactEvent]) -> str:
    """把一批交互事件渲染成 `known_objects` 文本段。

    后置条件：空输入返回空串（调用方据此知道这张地图还没有任何记录）；
    每个事件独立成行、按 step 升序（同 step 保持传入顺序），行与行之间
    单换行——行的粒度就是事件的粒度，没有第二条隐藏信息。
    """
    # 步骤 1：按 step 升序排（稳定排序保住同 step 事件的写入顺序）。
    ordered = sorted(events, key=lambda e: e.step)
    # 步骤 2：逐事件一行。
    return "\n".join(_render_line(e) for e in ordered)


def _render_line(event: ObjectFactEvent) -> str:
    """一条事件一行：ep/step → 站在哪按了什么 → 对什么：结果。"""
    if isinstance(event, ObjectDialogEvent):
        outcome = f'对话"{event.text}"'
    elif isinstance(event, ObjectWarpEvent):
        outcome = f"进入新地图{event.map_id}"
    elif isinstance(event, ObjectStillEvent):
        outcome = "无效果"
    else:  # pragma: no cover - 事件是封闭集合，新增类型时这里必须跟着加
        outcome = str(event)
    actor = event.actor_place
    cell = event.place
    return (
        f"{event.episode_id} step{event.step} "
        f"站在 x={actor.x} y={actor.y} 按 {event.button} → "
        f"地图{cell.map_id} x={cell.x} y={cell.y} 的{event.object_kind}：{outcome}"
    )
