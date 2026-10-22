"""保守规则预标；只读请求与感知证据，不读取模型响应。所有结果仍须人工审核。"""

from __future__ import annotations

import re
from collections import deque

from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq


def walking_keys(walk_map: str, start: tuple[int, int], criteria: str) -> list[str]:
    """返回可见普通地面内通往唯一明确坐标的最短路首键；门、台阶均留待人工。"""
    targets = re.findall(r"x\s*=\s*(\d+)\s*[,，]?\s*y\s*=\s*(\d+)", criteria)
    if len(targets) != 1 or re.search(r"!=|≠|>=|<=|至少|以上|以下", criteria):
        return []
    target = tuple(map(int, targets[0]))
    grid: dict[tuple[int, int], str] = {}
    for y, cells, left, right in re.findall(
        r"y=(-?\d+)\s+(\S+)\s+\(x=(-?\d+)\.\.(-?\d+)\)", walk_map
    ):
        if len(cells) != int(right) - int(left) + 1:
            return []
        grid.update({(int(left) + index, int(y)): cell for index, cell in enumerate(cells)})
    if grid.get(start) != "@" or grid.get(target) not in {".", "G", "I"}:
        return []
    distances = {target: 0}
    queue = deque([target])
    directions = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    while queue:
        x, y = queue.popleft()
        for dx, dy in directions.values():
            point = (x + dx, y + dy)
            if grid.get(point) in {".", "G", "I", "@"} and point not in distances:
                distances[point] = distances[(x, y)] + 1
                queue.append(point)
    if start not in distances:
        return []
    return [
        key
        for key, (dx, dy) in directions.items()
        if distances.get((start[0] + dx, start[1] + dy)) == distances[start] - 1
    ]


def candidate_keys(req: FromHarnessToBrainToolChooseOnceReq) -> tuple[list[str], str]:
    """只提出有明确局部证据的按键候选；候选并非完备真值集合。"""
    facts = req.obs.facts
    if req.obs.scene == "battle_menu":
        return [], "按交接约定，battle_menu 全部由人工标注"
    if facts.overlay == "dialog" and facts.dialog_text and not facts.options:
        keys, reason = ["a"], "无选项文本框，单次推进；仍需审核是否目标已满足"
    elif facts.overlay == "choice":
        keys, reason = menu_keys(req)
    elif facts.overlay == "none" and req.obs.scene == "walk" and req.obs.place:
        keys = walking_keys(
            (facts.model_extra or {}).get("walk_map", ""),
            (req.obs.place.x, req.obs.place.y),
            req.goals[-1].criteria,
        )
        reason = "唯一目标坐标，可见普通地面最短路；脚本、台阶与屏外路线需人工补审"
    else:
        keys, reason = [], "场景或目标不能由当前保守规则确定"
    return [key for key in keys if req.space.mask.get(key, False)], reason


def menu_keys(req: FromHarnessToBrainToolChooseOnceReq) -> tuple[list[str], str]:
    """只确认目标唯一且当前光标已到位的菜单；导航、否定与多目标交人工。"""
    facts = req.obs.facts
    goal = req.goals[-1].goal
    if any(word in goal for word in ("不要", "取消", "然后停", "停手", "不确认")):
        return [], "否定、取消或只移动目标，需人工判定"
    mentioned = [option for option in facts.options if option.casefold() in goal.casefold()]
    if (
        len(mentioned) == 1
        and mentioned[0] == facts.cursor
        and any(word in goal for word in ("确认", "选择", "选中", "按 a", "按a"))
    ):
        return ["a"], "目标项唯一且等于解码光标，单次确认；需补审脚本替代"
    if "第一个招式" in goal and facts.options and facts.cursor == facts.options[0]:
        return ["a"], "明确第一个招式且光标已到位；需人工核对战斗策略"
    return [], "菜单目标、布局导航或数量框需人工判定"
