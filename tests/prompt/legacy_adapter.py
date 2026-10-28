"""测试用对象交互文本解析器；只恢复文本实际携带的字段。"""

from __future__ import annotations

import re

from pydantic import JsonValue


class UnrestorableRequest(ValueError):
    """某个旧文本字段不能经现有渲染器精确重建。"""


def restore_object_events(text: str) -> list[dict[str, JsonValue]]:
    """只还原旧文本实际包含的字段，缺失的 actor map/run 不补造。"""
    pattern = re.compile(
        r"(?m)^(.+?) step(\d+) 站在 x=(-?\d+) y=(-?\d+) 按 (.+?) → "
        r"地图(-?\d+) x=(-?\d+) y=(-?\d+) 的(.+?)："
    )
    matches = list(pattern.finditer(text))
    if not matches or matches[0].start() != 0:
        raise UnrestorableRequest("known_objects 不是现行事件文本")
    events: list[dict[str, JsonValue]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() - 1 if i + 1 < len(matches) else len(text)
        outcome = text[match.end() : end]
        event: dict[str, JsonValue] = {
            "episode_id": match[1],
            "step": int(match[2]),
            "actor_place": {"x": int(match[3]), "y": int(match[4])},
            "button": match[5],
            "place": {"map_id": int(match[6]), "x": int(match[7]), "y": int(match[8])},
            "object_kind": match[9],
        }
        if outcome.startswith('对话"') and outcome.endswith('"'):
            event.update(outcome="dialog", text=outcome[3:-1])
        elif re.fullmatch(r"进入新地图-?\d+", outcome):
            event.update(outcome="warp", map_id=int(outcome.removeprefix("进入新地图")))
        elif outcome == "无效果":
            event["outcome"] = "still"
        else:
            raise UnrestorableRequest("known_objects 结果不可无损恢复")
        events.append(event)
    if [event["step"] for event in events] != sorted(event["step"] for event in events):
        raise UnrestorableRequest("known_objects 未按步号排序")
    return events
