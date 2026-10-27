"""相邻观察的机械差异；不访问存储，也不持有跨调用状态。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class Place(BaseModel):
    """观察时的地图坐标。"""

    map_id: int
    x: int
    y: int


class FacingObject(BaseModel):
    """观察时面朝的物体及其所在格。"""

    kind: str
    place: Place


class Ram(BaseModel):
    """差异计算所需的 RAM 片段。"""

    money: int
    bag: list[dict[str, int]]
    party: list[dict[str, str | int]]


class Snapshot(BaseModel):
    """只抽取差异规则所需的观察字段。"""

    step: int
    place: Place | None = None
    scene: str = ""
    overlay: str = ""
    dialog_text: str = ""
    ram: Ram | None = None
    facing_object: FacingObject | None = None
    settled: bool = True


@dataclass(frozen=True)
class Change:
    """一条由相邻观察机械得出的差异，不包含模型推断。"""

    kind: Literal["dialog_line", "warp", "money", "bag", "party", "scene"]
    step: int
    place: Place | None
    object: FacingObject | None
    text: str


def _snapshot(observation: BaseModel) -> Snapshot:
    """接受完整观察或紧凑观察，转换为本模块独立的字段形状。"""
    data = observation.model_dump(mode="json")
    facts = data.get("facts") or {}
    return Snapshot.model_validate(
        {
            "step": data["step"],
            "place": data.get("place"),
            "scene": data.get("scene") or facts.get("scene") or "",
            "overlay": data.get("overlay") or facts.get("overlay") or "",
            "dialog_text": data.get("dialog_text", facts.get("dialog_text", "")),
            "ram": data.get("ram"),
            "facing_object": data.get("facing_object"),
            "settled": data.get("settled", True),
        }
    )


def changes(prev: BaseModel, next: BaseModel) -> list[Change]:
    """比较相邻完整或紧凑观察；未稳定的后帧文字不作为对话证据。"""
    before, after = _snapshot(prev), _snapshot(next)
    result: list[Change] = []

    def add(
        kind: Literal["dialog_line", "warp", "money", "bag", "party", "scene"], text: str
    ) -> None:
        result.append(Change(kind, after.step, after.place, after.facing_object, text))

    if after.settled:
        previous_lines = set(before.dialog_text.splitlines())
        for line in after.dialog_text.splitlines():
            if line.strip() and line not in previous_lines:
                add("dialog_line", line)
    if (
        before.place is not None
        and after.place is not None
        and before.place.map_id != after.place.map_id
    ):
        add("warp", f"{before.place.map_id} → {after.place.map_id}")
    if before.ram is not None and after.ram is not None:
        if before.ram.money != after.ram.money:
            add("money", f"{before.ram.money} → {after.ram.money}")
        for field in ("bag", "party"):
            old, new = getattr(before.ram, field), getattr(after.ram, field)
            if old != new:
                add(
                    field,
                    f"{json.dumps(old, ensure_ascii=False)} → "
                    f"{json.dumps(new, ensure_ascii=False)}",
                )
    if (before.scene, before.overlay) != (after.scene, after.overlay):
        add("scene", f"{before.scene}/{before.overlay} → {after.scene}/{after.overlay}")
    return result


__all__ = ["Change", "changes"]
