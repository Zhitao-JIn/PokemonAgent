"""从每次 choose 的实际目标和当前地图提出补救建议；不保证唯一或必然成功。"""

from evals.dataset.brain_calls.dataset_contract import InputCase

from .choose_movement import route


def recovery(case: InputCase) -> tuple[list[str], str]:
    """仅覆盖本轮已审失败现场；没有审阅的场景显式失败，不默认建议按 a。"""
    sample, _, _, number = case.case_id.split(".")
    number = int(number)
    request, facts = case.request, case.request.obs.facts
    place = request.obs.place
    if sample == "knowledge_battle_action_menu":
        if facts.overlay == "dialog":
            return [
                "a"
            ], "先推进/关闭逃跑字幕。字幕关闭不代表回到战斗菜单，之后可另找合理恢复路径。"
        return ["up", "down", "right"], (
            "当前已是草丛附近的 field，继续 a 无效。本次请求只要求回到行动菜单，"
            "并未包含原 L1 的禁止重新遇敌条款；沿可见草格重新遇敌是可接受的恢复候选。"
        )
    if sample == "knowledge_pokemon_center_heal" and number <= 10:
        if (place.x, place.y) != (3, 3):
            return route((facts.model_extra or {}).get("walk_map", ""), place.x, place.y, (3, 3)), (
                "目标(3,2)是 #；可先回可走的(3,3)，再朝目标人物核实柜台互动。"
            )
        return ["a"] if facts.facing == "north" else ["up"], (
            "不再尝试站进(3,2)墙格；在柜台外朝北试一次互动，或调查其他合法站位，"
            "均可按当前证据评估。人物身份和治疗尚未证实。"
        )
    if sample == "knowledge_pokemon_center_heal":
        return ["up"], (
            "当前在门附近但仍地图41，允许先向北退一格，再从不同接近方向重新调查 D 门；"
            "也可选择有当前能力和地图依据的其他出口探测。不要声称触发机制已知或保证传送。"
        )
    if sample == "knowledge_shop_interaction":
        return merchant(case, number)
    raise ValueError(f"unreviewed recovery: {case.case_id}")


def merchant(case: InputCase, number: int) -> tuple[list[str], str]:
    """错误人物、墙格与对话循环分别给出可替代调查方向。"""
    obs = case.request.obs
    if obs.facts.overlay == "dialog":
        return ["a"], (
            "单次关闭/读完当前普通或售罄对话是可接受的准备动作；关闭后不要再次开启同一无效循环，"
            "允许转查其他人物或柜台。不能凭一次推进断言商店菜单将出现。"
        )
    if 16 <= number <= 25 or 46 <= number <= 51:
        return route(
            (obs.facts.model_extra or {}).get("walk_map", ""), obs.place.x, obs.place.y, (3, 4)
        ), (
            "当前子目标把 D 当人物或要求站到 #。可转向可走的(3,4)调查当前可见(3,3)人物，"
            "也可选择其他可见人物/柜台验证身份；建议坐标不代表已确认店员。"
        )
    if obs.place.x >= 5:
        return ["left"], (
            "同一人物的介绍对话已循环；可沿西侧可走地面离开错误交互对象，调查其他可见柜台/人物。"
            "不限定唯一方向或唯一人物，但不能无证据重复 a 期待菜单。"
        )
    return ["left", "down"], (
        "当前朝北人物已只返回售罄；允许离开该交互点，沿可走地面调查其他可见人物/柜台或前提条件，"
        "而不是原地重复 a。候选方向是建议，不保证一步找到正确店员。"
    )
