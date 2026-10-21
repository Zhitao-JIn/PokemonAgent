"""已审阅的有限菜单判据；仅严格匹配列出的完整句式。"""

import re

from pokemon_agent.world import TaskObservation


def menu_truth(current: TaskObservation, criterion: str) -> tuple[bool, str] | None:
    """不识别的句式返回 None；菜单别名 BAG/ITEM、POKEMON/PKMN 等义。"""
    facts = current.facts
    shop = {"BUY", "SELL", "QUIT"} <= set(facts.options)
    battle = str(current.scene).startswith("battle")
    main = battle and {"FIGHT", "PKMN", "ITEM", "RUN"} <= set(facts.options)
    if criterion in (
        "画面出现 BUY / SELL / QUIT 选项列表",
        "选项里出现 BUY / SELL / QUIT",
        "屏幕出现 BUY / SELL / QUIT 选项列表",
    ):
        return shop, "shop_options"
    if criterion == "对话框出现文字，或屏幕出现 BUY / SELL / QUIT 选项":
        return bool(facts.dialog_text) or shop, "dialog_or_shop_options"
    if criterion == "对话框消失（叠加层不再是 dialog），或出现 BUY/SELL/QUIT 选项":
        return facts.overlay != "dialog" or shop, "not_dialog_or_shop_options"
    if criterion == "画面出现战斗界面，底部行动菜单显示 FIGHT/BAG/POKEMON/RUN 等选项":
        return main, "battle_main_options_aliases"
    if criterion == "屏幕底部出现 FIGHT/BAG/POKEMON/RUN 选项且光标在 FIGHT":
        return main and facts.cursor == "FIGHT", "battle_fight_cursor"
    if criterion == "overlay 不再是 dialog，屏幕出现 FIGHT/PKMN/ITEM/RUN 选项":
        return facts.overlay != "dialog" and main, "battle_main_not_dialog"
    if criterion == "屏幕出现 FIGHT/BAG/POKEMON/RUN 选项，或叠加层不再是 dialog":
        return main or facts.overlay != "dialog", "battle_main_or_not_dialog"
    if criterion == "场景显示 battle，或屏幕出现战斗界面":
        return battle, "battle_scene"
    cursor = re.fullmatch(r"光标显示在 (ITEM|PKMN) 上", criterion)
    if cursor:
        return facts.cursor == cursor[1], "menu_cursor"
    if criterion == "光标显示为 RUN（选项仍为 FIGHT/PKMN/ITEM/RUN，场景仍为 battle）":
        return main and facts.cursor == "RUN", "battle_run_cursor"
    if criterion == "光标显示为 RUN，且场景仍是 battle、叠加层仍是 choice":
        return battle and facts.overlay == "choice" and facts.cursor == "RUN", "battle_run_choice"
    return None
