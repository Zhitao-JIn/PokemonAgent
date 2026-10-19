"""八十三个待审判定现场的独立裁决；仅使用同请求已见状态。"""

from evals.dataset.brain_calls.dataset_contract import InputCase


def review(case: InputCase) -> tuple[bool, str]:
    """已审场景给明确真值；新场景失败关闭，不能默认算未达成。"""
    scenario, layer, _, number = case.case_id.split(".")
    number = int(number)
    if scenario in {
        "knowledge_battle_fight_menu",
        "knowledge_battle_item_use",
        "knowledge_battle_move_select",
        "knowledge_battle_pokemon_switch",
        "knowledge_shop_open_buy_menu",
        "knowledge_shop_select_item",
    }:
        return (
            True,
            (
                "当前选项/屏幕已变成目标所需的招式、道具、队伍、商品或数"
                "量界面；不是仅停在父菜单光标。"
            ),
        )
    if scenario == "knowledge_battle_run_attempt":
        return number == 2, {
            1: "当前是 PKMN 光标，要求 RUN；尚未到位。",
            2: "当前 choice 的光标已到 RUN，满足本次仅移动光标的标准。",
            3: (
                "仍是 battle 且文字为 Got away safel；标准要求已回到 fiel"
                "d 或出现逃跑失败文字，不能提前放宽为正在逃跑。"
            ),
        }[number]
    if scenario == "knowledge_catch_throw_ball":
        return number in {4, 12}, (
            "前缀历史 ITEM 确认后已出现 POTION/POKé BALL 背包列表。"
            if number == 4
            else (
                "当前完整 Aww! It appeared to be caught! 含 caught，满足"
                "本任务文字标准；不等于捕获成功。"
            )
            if number == 12
            else (
                "当前仅移动光标、投球使用动画或未完成的 Aww! It app，不满"
                "足本次所要求的背包/投球结算文字。"
            )
        )
    return review_world(scenario, layer, number)


def review_world(scenario: str, layer: str, number: int) -> tuple[bool, str]:
    """当前地图、血量与治疗状态的请求内证据裁决。"""
    if scenario == "knowledge_catch_weaken_target":
        return True, (
            "当前已出现 TACKLE/GROWL/LEECH SEED 招式列表。"
            if number == 1
            else (
                "本次 history 的 before.foe_hp=15/15，after.foe_hp=10/15"
                "；直接数值证据证明伤害，不靠招式名称猜。"
            )
        )
    if scenario == "knowledge_pokemon_center_enter":
        return (
            number == 5,
            (
                "以本请求 before/after 的地图号判定：前四次仍是地图1，第"
                "五次已从地图1进入地图41；走近门不算进入。"
            ),
        )
    if scenario == "knowledge_pokemon_center_heal":
        return False, (
            (
                "当前及所给历史未提供护士/治疗完成的正证据；失败状态章不"
                "支持达成，不从派生叙述补造治疗事件。"
            )
            if layer != "task"
            else "要求站到(3,2)朝北，实际坐标不符；目标前提错误也不能把未满足的标准判为真。"
            if number <= 10
            else "所见是介绍其他城镇宝可梦中心的普通 NPC 对话，不是护士治疗完成文字。"
            if number <= 23
            else (
                "历史每次 before/after 都为地图41、walk、overlay=none；坐"
                "标变化不等于所要求的地图/场景/叠加层变化。"
            )
        )
    return review_shop(scenario, number)


def review_shop(scenario: str, number: int) -> tuple[bool, str]:
    """商店的数量、确认、取消、完成阶段分别裁决。"""
    if scenario == "knowledge_shop_cancel_purchase":
        return number in {3, 6, 7, 10, 12}, {
            1: "光标 SELL，还未 QUIT 并确认。",
            2: "光标 QUIT，但尚未确认退出。",
            3: ("历史 QUIT 后确认，当前 Thank you!，满足退出子任务；不代表原始取消购买目标完成。"),
            4: "菜单已关闭，未重新打开 BUY/SELL/QUIT。",
            5: "只有商人问候的部分文字，未出现目标选项。",
            6: "BUY/SELL/QUIT 已出现，光标 BUY。",
            7: "当前已变成 POKé BALL 等商品列表。",
            8: "只有数量框，尚无 YES/NO。",
            9: "只有报价过程文字，尚无 YES/NO。",
            10: "当前 YES/NO 确认框已出现。",
            11: "光标 NO 仍在确认框，尚未取消返回商品。",
            12: "历史 NO 确认后 YES/NO 消失，商品选项重新出现。",
        }[number]
    if scenario == "knowledge_shop_confirm_purchase":
        return number in {3, 4}, (
            "数量框或部分报价不是 YES/NO 购买确认选项，也没有购买完成文字。"
            if number < 3
            else "当前 YES/NO 出现，符合本次子任务标准中的购买确认选项分支。"
            if number == 3
            else (
                "当前 Here you 完成提示，历史 YES 确认后 YES/NO 消失，屏"
                "幕金额由3000减至2800；已有同请求购买完成证据。"
            )
        )
    if scenario == "knowledge_shop_interaction":
        return number == 45, (
            (
                "同任务历史包含重新触发的对话，当前 overlay=none，符合‘对"
                "话框再次消失’分支，不表示商店菜单已出现。"
            )
            if number == 45
            else (
                "当前仍是 This shop sells many ANTIDOTEs 对话，无 BUY/SEL"
                "L/QUIT，且对话尚未再次消失。"
            )
        )
    raise ValueError(f"unreviewed judge case: {scenario}.{number}")
