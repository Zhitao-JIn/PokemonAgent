"""严格匹配已审阅的显式状态判据；未知自然语言不猜测，不读旧模型响应。"""

import re
from typing import TypeAlias

from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from pokemon_agent.world import TaskObservation

from .visible_menus import menu_truth
from .visible_transactions import catch_result_truth, transaction_truth

Decision: TypeAlias = tuple[bool, str, str] | None


def visible_judge(request: FromHarnessToBrainToolJudgeReq) -> Decision:
    """当前状态标签；未知判据或缺字段返回不可判，不把缺证据当未达成。"""
    current = request.observation or (request.history[-1].after if request.history else None)
    if current is None:
        return None
    criterion = request.goal.criteria.strip()
    locator = (
        "request.observation" if request.observation is not None else "request.history[-1].after"
    )
    position = _position(current, criterion, locator)
    if position is not None:
        return position
    transaction = transaction_truth(current, criterion) or catch_result_truth(current, criterion)
    if transaction is not None:
        return transaction[0], transaction[1], locator + ".facts.screen"
    menu = menu_truth(current, criterion)
    if menu is not None:
        return menu[0], menu[1], locator + ".facts"
    text = _text(current, criterion, locator)
    if text is not None:
        return text
    if (
        criterion
        in (
            "对话框消失（overlay 不是 dialog），且历史里出现过 dialog_text",
            "历史里出现过 dialog_text，且这一帧 overlay 不是 dialog",
        )
        and request.history
    ):
        had_dialog = any(
            memory.before.facts.dialog_text or memory.after.facts.dialog_text
            for memory in request.history
        )
        return (
            bool(had_dialog) and current.facts.overlay != "dialog",
            "dialog_finished",
            "request.history",
        )
    return None


def _position(current: TaskObservation, criterion: str, locator: str) -> Decision:
    """只匹配明确坐标与地图条件；不允许多余 OR 等未解释条件。"""
    position = re.fullmatch(r"where\s*显示\s*x=(\d+)\s+y=(\d+)", criterion)
    if position:
        if current.place is None:
            return None
        expected = (int(position[1]), int(position[2]))
        actual = (current.place.x, current.place.y)
        return actual == expected, "exact_coordinates", locator + ".place"
    not_map = re.fullmatch(r"map_id\s*不再是\s*(\d+)", criterion)
    if not_map and current.facts.map_id is not None:
        return (
            current.facts.map_id != int(not_map[1]),
            "different_map_id",
            locator + ".facts.map_id",
        )
    map_y = re.fullmatch(
        r"where\s*(?:那一行)?显示\s*map_id\s*仍是\s*(\d+)\s*且\s*y\s*(>=|=)\s*(\d+)",
        criterion,
    )
    if map_y and current.place is not None and current.facts.map_id is not None:
        y_ok = (
            current.place.y >= int(map_y[3])
            if map_y[2] == ">="
            else current.place.y == int(map_y[3])
        )
        return current.facts.map_id == int(map_y[1]) and y_ok, "map_and_y", locator + ".place"
    return None


def _text(current: TaskObservation, criterion: str, locator: str) -> Decision:
    """只判明确菜单／对话／野生遭遇的可见状态。"""
    facts = current.facts
    shop = re.fullmatch(
        r"overlay\s*是\s*choice[，,]\s*且\s*options\s*(?:含|是)\s*BUY\s*/\s*SELL\s*/\s*QUIT",
        criterion,
    )
    if shop:
        matched = facts.overlay == "choice" and {"BUY", "SELL", "QUIT"} <= set(facts.options)
        return matched, "shop_menu", locator + ".facts"
    if criterion in ("overlay 是 dialog，且 dialog_text 非空", "对话非空（对话框里出现对方的话）"):
        matched = bool(facts.dialog_text)
        if criterion.startswith("overlay"):
            matched = matched and facts.overlay == "dialog"
        return matched, "dialog_visible", locator + ".facts"
    if re.fullmatch(
        r"scene\s*是\s*battle[，,]\s*或对话框里出现\s*WILD \.\.\. appeared!",
        criterion.replace(chr(96), ""),
    ):
        matched = str(current.scene).startswith("battle") or bool(
            re.search(r"WILD\s+.+\s+appeared!", facts.dialog_text, flags=re.IGNORECASE)
        )
        return matched, "wild_battle_visible", locator
    return None
