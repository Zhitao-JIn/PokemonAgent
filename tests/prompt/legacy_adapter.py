"""测试专用的一次性历史适配；逐字段使用旧渲染器证明无损，不补造历史语义。"""

from __future__ import annotations

import copy
import re

from pydantic import BaseModel, JsonValue, ValidationError

from pokemon_agent.world import PlaceInWorld, ScreenText, TerrainMap
from pokemon_agent.world.interface.domain.battle_status import BattleStatus


class UnrestorableRequest(ValueError):
    """某个旧文本字段不能经现有渲染器精确重建。"""


class AdaptedRequest(BaseModel):
    """测试边界返回的增强请求及处理过的观测数。"""

    request: dict[str, JsonValue]
    observations: int


def restore_observation(observation: dict[str, JsonValue]) -> None:
    """保留旧字段，增加结构化原料；任何往返不一致均显式拒绝。"""
    facts = observation["facts"]
    if not isinstance(facts, dict):
        raise UnrestorableRequest("facts 不是对象")
    where = facts.get("where", "")
    place = observation.get("place")
    if where:
        match = re.fullmatch(r"全局坐标 地图(-?\d+) x=(-?\d+) y=(-?\d+)", str(where))
        if match is None:
            raise UnrestorableRequest("where 不是现行 PlaceInWorld 文本")
        parsed = PlaceInWorld(map_id=int(match[1]), x=int(match[2]), y=int(match[3]))
        if parsed.render() != where:
            raise UnrestorableRequest("where 往返不一致")
        place = parsed.model_dump(mode="json")
        observation["place"] = place
    neighbors = facts.get("neighbors", "")
    if neighbors:
        match = re.fullmatch(r"北 (.) 南 (.) 西 (.) 东 (.)", str(neighbors))
        if match is None:
            raise UnrestorableRequest("neighbors 不是现行四邻文本")
        facts["neighbor_cells"] = dict(
            zip(("up", "down", "left", "right"), match.groups(), strict=True)
        )
    walk_map = facts.get("walk_map", "")
    facts["terrain_visible"] = bool(walk_map)
    if walk_map:
        rows = str(walk_map).splitlines()
        parsed_rows = [
            re.fullmatch(r"y=(-?\d+)\s+([.#GDSNIBv<>@]{10})  \(x=(-?\d+)\.\.(-?\d+)\)", row)
            for row in rows[1:]
        ]
        if len(parsed_rows) != 9 or not all(parsed_rows) or not isinstance(place, dict):
            raise UnrestorableRequest("walk_map 缺少九行十列或结构化位置")
        cells = [match[2] for match in parsed_rows]
        terrain = TerrainMap(
            cells=cells,
            map_id=int(str(place["map_id"])),
            player_x=int(str(place["x"])),
            player_y=int(str(place["y"])),
        )
        if terrain.render() != walk_map:
            raise UnrestorableRequest("walk_map 往返不一致")
        facts["cells"] = cells
        if neighbors and terrain.render_neighbors() != neighbors:
            raise UnrestorableRequest("地形与四邻矛盾")
    layout = facts.get("option_layout", "")
    if layout:
        lines = str(layout).splitlines()
        grid: list[list[str]] = []
        cursor: tuple[int, int] | None = None
        for row, line in enumerate(lines[1:]):
            items = re.split(r" {2}(?=[ ▶])", line)
            grid.append([item[1:] for item in items])
            for col, item in enumerate(items):
                if item.startswith("▶"):
                    cursor = (row, col)
        screen = ScreenText(option_grid=grid, cursor_cell=cursor)
        if screen.render_layout() != layout:
            raise UnrestorableRequest("option_layout 往返不一致")
        facts["option_grid"] = grid
        facts["cursor_cell"] = list(cursor) if cursor is not None else None
    details = facts.get("option_details", "")
    if details:
        options = facts.get("options", [])
        if not isinstance(options, list):
            raise UnrestorableRequest("options 不是列表")
        annotations = [""] * len(options)
        for part in str(details).split(" / "):
            matches = [i for i, option in enumerate(options) if part.startswith(str(option) + " ")]
            if len(matches) != 1:
                raise UnrestorableRequest("option_details 无法关联选项")
            index = matches[0]
            annotations[index] = part[len(str(options[index])) + 1 :]
        screen = ScreenText(options=options, option_details=annotations)
        if screen.render_details() != details:
            raise UnrestorableRequest("option_details 往返不一致")
        facts["option_annotations"] = annotations
    battle_keys = [
        prefix + "_" + key for prefix in ("my", "foe") for key in ("name", "level", "hp", "status")
    ]
    if any(key in facts for key in battle_keys):
        if not all(key in facts for key in battle_keys):
            raise UnrestorableRequest("战斗状态字段不完整")
        sides = {}
        for prefix, name in (("my", "mine"), ("foe", "foe")):
            hp, maximum = str(facts[prefix + "_hp"]).split("/")
            sides[name] = {
                "name": facts[prefix + "_name"],
                "level": int(str(facts[prefix + "_level"])),
                "hp": int(hp),
                "max_hp": int(maximum),
                "status": facts[prefix + "_status"],
            }
        battle = BattleStatus.model_validate(sides)
        if any(battle.facts_fields()[key] != facts[key] for key in battle_keys):
            raise UnrestorableRequest("战斗状态往返不一致")
        facts["battle_status"] = battle.model_dump(mode="json")


def adapt_request(request: dict[str, JsonValue]) -> AdaptedRequest:
    """递归转换请求中的观测，失败不返回半份增强数据。"""
    adapted = copy.deepcopy(request)
    observations = 0

    def visit(value: JsonValue) -> None:
        nonlocal observations
        if isinstance(value, dict):
            if "facts" in value and "step" in value and "status" in value:
                restore_observation(value)
                observations += 1
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    try:
        visit(adapted)
    except (ValidationError, TypeError, KeyError, ValueError) as error:
        if isinstance(error, UnrestorableRequest):
            raise
        raise UnrestorableRequest(str(error)) from error
    return AdaptedRequest(request=adapted, observations=observations)
