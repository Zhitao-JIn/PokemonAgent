"""战斗主菜单仅移光标的独立标签；确认会越过目标，脚本不视为等价。"""

import re

from evals.dataset.brain_choose.schemas import ActionMatcher

from .dataset_contract import InputCase

TARGETS: dict[str, str] = {
    "光标显示在 ITEM 上": "ITEM",
    "光标显示在 PKMN 上": "PKMN",
    "光标显示为 RUN（选项仍为 FIGHT/PKMN/ITEM/RUN，场景仍为 battle）": "RUN",
    "光标显示为 RUN，且场景仍是 battle、叠加层仍是 choice": "RUN",
    "scene 是 battle、overlay 是 choice，且 cursor 是 RUN": "RUN",
}


def cursor_actions(case: InputCase) -> tuple[list[ActionMatcher], str]:
    """目标仅为光标位置且现场布局完整时，允许通向目标的单次方向键。"""
    request = case.request
    facts = request.obs.facts
    target = TARGETS.get(request.goals[-1].criteria.strip())
    expected = ["FIGHT", "PKMN", "ITEM", "RUN"]
    layout = str(getattr(facts, "option_layout", ""))
    if (
        target is None
        or facts.options != expected
        or facts.cursor not in expected
        or facts.overlay != "choice"
        or not str(request.obs.scene).startswith("battle")
        or re.match(r"2 行 × 2 列，光标在第 [12] 行第 [12] 列", layout) is None
    ):
        return [], "不是可证明的仅移动主菜单光标目标"
    current_row, current_column = divmod(expected.index(facts.cursor), 2)
    target_row, target_column = divmod(expected.index(target), 2)
    keys = []
    if current_row != target_row:
        keys.append("down" if target_row > current_row else "up")
    if current_column != target_column:
        keys.append("right" if target_column > current_column else "left")
    return (
        [ActionMatcher(key=key, max_times=1) for key in keys if request.space.enabled(key)],
        "完整 2×2 主菜单布局；目标只要求光标到位，单次方向键缩短行列距离。"
        "a 与 battle_run 等确认/执行脚本会越过目标，不列为等价答案。",
    )
