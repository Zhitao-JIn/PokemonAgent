"""当前目标、菜单、地图与同任务前缀上的单步审阅；无 baseline 读取。"""

from evals.dataset.brain_calls.dataset_contract import InputCase
from evals.dataset.brain_choose.schemas import ActionMatcher

from .choose_interactions import Decision, merchant, nurse
from .choose_movement import route
from .contract import Annotation
from .evidence import collect

DIRECTION: dict[str, str] = {"up": "north", "down": "south", "left": "west", "right": "east"}


def menu_keys(scenario: str, number: int) -> list[str]:
    """审阅过的菜单动作表；未登记序号失败关闭，不猜默认 a。"""
    tables: dict[str, dict[int, list[str]]] = {
        "battle_fight_menu": {1: ["a"]},
        "battle_item_use": {2: ["a"]},
        "battle_move_select": {1: ["a"], 2: ["a"], 3: ["a"], 4: ["a"]},
        "battle_pokemon_switch": {2: ["a"]},
        "battle_run_attempt": {1: ["down", "right"], 2: ["down"], 3: ["a"]},
        "catch_throw_ball": {
            1: ["down"],
            2: ["left", "down"],
            3: ["left"],
            4: ["a"],
            5: ["down"],
            **{index: ["a"] for index in range(6, 13)},
        },
        "catch_weaken_target": {1: ["a"], 2: ["a"]},
        "shop_cancel_purchase": {
            1: ["down"],
            2: ["down"],
            3: ["a"],
            4: ["a"],
            5: ["a"],
            6: ["a"],
            7: ["a"],
            8: ["a"],
            9: ["a"],
            10: ["a"],
            11: ["down"],
            12: ["a", "b"],
        },
        "shop_confirm_purchase": {index: ["a"] for index in range(1, 5)},
        "shop_open_buy_menu": {1: ["a"]},
        "shop_select_item": {1: ["a"]},
        "dialogue_advance": {1: ["a"]},
        "npc_dialogue": {3: ["up"], 4: ["a"]},
    }
    return tables[scenario][number]


def decision(case: InputCase) -> Decision:
    """新场景没有审阅记录则抛异常；已满足且无 stop 工具的现场单独排除。"""
    sample, _, _, index = case.case_id.split(".")
    scenario, number = sample.removeprefix("knowledge_"), int(index)
    obs = case.request.obs
    if scenario == "shop_interaction":
        return merchant(number)
    if scenario == "pokemon_center_heal":
        return nurse(number, obs.facts.overlay)
    if scenario == "battle_action_menu":
        return battle_intro(number)
    if scenario == "door_transition" or scenario == "pokemon_center_enter":
        target = (13, 5) if scenario == "door_transition" else (23, 25)
        keys = route(obs.facts.walk_map, obs.place.x, obs.place.y, target)
        return (
            "labelled",
            keys,
            f"当前可见路径到门{target}；只目标门作为可进入终点，避开 #/S/N，"
            "经可走地面接近；不把到门前当传送完成。",
        )
    if scenario == "movement_obstacle":
        return (
            "labelled",
            ["down"],
            ("当前南邻 v，能力说明允许顺向跳下台阶；单次 down 前进至 y14，不把 v 误判成墙。"),
        )
    if scenario == "wild_encounter":
        return (
            "labelled",
            ["up", "down", "left"],
            "当前东邻 #，其余所列方向是可见 G 草格；移动草格遇敌，不能向东撞墙。",
        )
    keys = menu_keys(scenario, number)
    return (
        "labelled",
        keys,
        (
            "按当前布局与目标层级选择单步：只打开列表不能使用道具/攻"
            "击/换人；确认需等光标到位，数量框不跳过，取消需 NO，出场"
            "/投球动画只推进本帧。"
        ),
    )


def battle_intro(number: int) -> Decision:
    """重遇敌是另一个可见目标；不从原 L1 跨范围导入禁止遇敌约束。"""
    if number == 3:
        return (
            "invalid_task",
            [],
            (
                "当前 RUN 光标已满足仅移动目标，却继续调用无 stop 的 choo"
                "se；a 会越界逃跑，应由上层结算。"
            ),
        )
    if 4 <= number <= 9:
        return (
            "invalid_task",
            [],
            (
                "已逃跑，当前 Got away/field；任务却要求只推进对话回当前"
                "战斗主菜单。结束逃跑对话不会恢复原战斗，需上层修正前提。"
            ),
        )
    if number == 12:
        return (
            "labelled",
            ["down", "right"],
            (
                "本次目标是草丛来回遇敌，当前南/东为 G；不能导入另一 L1 "
                "原 RUN 目标的禁止重遇敌条款。"
            ),
        )
    if 13 <= number <= 23:
        return (
            "labelled",
            ["a"],
            (
                "当前尚处战斗过渡/出场而非行动选择；单次推进到菜单，达到 "
                "criterion 后停止，不继续确认 FIGHT。"
            ),
        )
    raise ValueError(f"unreviewed intro choose {number}")


def equivalents(case: InputCase, keys: list[str]) -> list[ActionMatcher]:
    """只添加已核对前置条件的同层脚本，不用会越过本次目标的宏替代开菜单。"""
    req, name = case.request, case.case_id
    actions = [
        ActionMatcher(key=key, max_times=1, max_total_times=1)
        for key in keys
        if req.space.enabled(key)
    ]
    if keys == ["a"] and req.obs.facts.overlay == "none" and req.space.enabled("interact_facing"):
        actions.append(ActionMatcher(script="interact_facing"))
    if keys == ["a"] and req.obs.facts.overlay == "dialog" and req.space.enabled("advance_dialog"):
        actions.append(ActionMatcher(script="advance_dialog", args={"max_presses": 1}))
    if "battle_run_attempt" in name and name.endswith("000003") and req.space.enabled("battle_run"):
        actions.append(ActionMatcher(script="battle_run"))
    if (
        ("battle_move_select" in name or "catch_weaken_target" in name)
        and name.endswith("000002")
        and req.space.enabled("battle_fight")
    ):
        actions.append(ActionMatcher(script="battle_fight", args={"move": "TACKLE"}))
    if (
        "catch_throw_ball" in name
        and name.endswith("000006")
        and req.space.enabled("battle_use_item")
    ):
        actions.append(ActionMatcher(script="battle_use_item", args={"item": req.obs.facts.cursor}))
    if any(key in DIRECTION for key in keys) and req.obs.facts.overlay == "none":
        for key in keys:
            if (
                key in DIRECTION
                and req.obs.facts.facing != DIRECTION[key]
                and req.space.enabled("face_direction")
            ):
                actions.append(
                    ActionMatcher(script="face_direction", args={"direction": DIRECTION[key]})
                )
    return actions


def review(case: InputCase) -> Annotation:
    """返回与原请求哈希绑定的动作集合或明确排除理由。"""
    status, keys, reason = decision(case)
    actions = equivalents(case, keys) if status == "labelled" else []
    if status == "labelled" and not actions:
        raise ValueError(f"review produced no enabled action: {case.case_id}")
    obs = case.request.obs
    context = (
        f"现场 {obs.facts.where}，{obs.scene}/{obs.facts.overlay}，"
        f"朝{obs.facts.facing}，光标{obs.facts.cursor}，文字{obs.facts.dialog_text!r}。"
    )
    return Annotation(
        case_id=case.case_id,
        family="choose",
        request_sha256=case.source.request_canonical_sha256,
        status=status,
        method="codex_history_review",
        rationale=context + reason,
        evidence=collect(case),
        acceptable=actions,
    )
