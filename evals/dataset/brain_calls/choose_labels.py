"""只给可由完整当前输入独立确认的动作集合；其余保留待审。"""

import re

from evals.dataset.brain_choose.build.prelabel import walking_keys
from evals.dataset.brain_choose.schemas import ActionMatcher

from .dataset_contract import InputCase
from .menu_labels import cursor_actions

DIRECTIONS: dict[str, str] = {"up": "north", "down": "south", "left": "west", "right": "east"}


def acceptable_actions(case: InputCase) -> tuple[list[ActionMatcher], str]:
    """精确坐标目标的局部最短路键及等价脚本；不读取已采集动作。"""
    menu, reason = cursor_actions(case)
    if menu:
        return menu, reason
    request = case.request
    observation = request.obs
    if observation.facts.overlay != "none" or observation.place is None:
        return [], "非纯移动现场，需逐例核对动作及等价脚本"
    if re.fullmatch(r"where\s*显示\s*x=\d+\s+y=\d+", request.goals[-1].criteria.strip()) is None:
        return [], "不是无附加条件的明确坐标目标"
    keys = walking_keys(
        (observation.facts.model_extra or {}).get("walk_map", ""),
        (observation.place.x, observation.place.y),
        request.goals[-1].criteria,
    )
    keys = [key for key in keys if request.space.mask.get(key, False)]
    if not keys:
        return [], "没有唯一可见坐标或普通地面的可证明路径"
    actions = [ActionMatcher(key=key, max_times=1) for key in keys]
    targets = re.findall(r"x\s*=\s*(\d+)\s*[,，]?\s*y\s*=\s*(\d+)", request.goals[-1].criteria)
    x, y = map(int, targets[0])
    if request.space.enabled("walk_to"):
        actions.append(ActionMatcher(script="walk_to", args={"x": x, "y": y}))
    for key in keys:
        if request.space.enabled("walk_to_adjacent"):
            actions.append(
                ActionMatcher(script="walk_to_adjacent", args={"direction": DIRECTIONS[key]})
            )
        if request.space.enabled("face_direction") and observation.facts.facing != DIRECTIONS[key]:
            actions.append(
                ActionMatcher(script="face_direction", args={"direction": DIRECTIONS[key]})
            )
    return (
        actions,
        "当前可见 walk_map 上唯一精确坐标目标：最短路首键、相邻移动、到目标的 walk_to，"
        "以及必要的转向。按键限制单次；不使用 baseline 动作。"
        "不适用于门、台阶、屏外路线或其他目标，非完整战略动作空间。",
    )
