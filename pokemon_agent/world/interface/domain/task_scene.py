"""task 层的场合（`TaskScene`）：人在哪、在做什么——决定给 JEV 什么观测、什么动作空间。

与 episode 层视觉链路的 `Facts.Scene` 是两套词表、两种观测，只是都叫"场景"，互不引用。
判别规则在 `world/scene.py::classify_scene`，词表与宏的对应见 `docs/perceive/spec.md` 第三、五节。
"""

from __future__ import annotations

from enum import StrEnum


class TaskScene(StrEnum):
    """一帧属于哪个场合。常规场合一键一决策；接管场合（`TAKEOVER_SCENES`）由宏执行到底。"""

    # ---- 常规 ----
    WALK = "walk"  # 走路，屏上没字
    DIALOG = "dialog"  # 野外 / 室内的对话（含对话里的单层 YES/NO）
    BATTLE = "battle"  # 战斗里选单以外的帧：战斗文字、单层 YES/NO、结算
    SHOP = "shop"  # 商店里还没打开买卖菜单：走动、和店员说话
    POKEMON_INFO = "pokemon_info"  # 单只宝可梦的信息页：能力页、图鉴条目页
    START_MENU = "start_menu"  # 开始菜单本身与图鉴目录、训练家卡片、选项
    TITLE = "title"  # 标题画面
    TRANSITION = "transition"  # 空框、淡入淡出、开场图形

    # ---- 接管 ----
    NAMING = "naming"  # 起名键盘
    SHOP_ITEMS = "shop_items"  # 商店买卖（MONEY 框在屏的一切帧）
    PC = "pc"  # PC 一打开起：选哪台 PC、道具存取、宝可梦存取、换箱
    BAG = "bag"  # 野外背包一打开起：列表、用 / 丢、选对象、数量框、城镇地图
    BATTLE_MENU = "battle_menu"  # 战斗里的选单：行动菜单、招式列表、战斗背包、换人列表
    FAINT_SWITCH = "faint_switch"  # 倒下后选下一只
    PARTY = "party"  # 野外队伍列表（开始菜单进的，含 STATS / SWITCH 子菜单）
    LEARN_MOVE = "learn_move"  # 学新招要忘旧招（含前面几句提示，RARE CANDY 触发实测）


TAKEOVER_SCENES: frozenset[TaskScene] = frozenset(
    {
        TaskScene.NAMING,
        TaskScene.SHOP_ITEMS,
        TaskScene.PC,
        TaskScene.BAG,
        TaskScene.BATTLE_MENU,
        TaskScene.FAINT_SWITCH,
        TaskScene.PARTY,
        TaskScene.LEARN_MOVE,
    }
)
"""由宏执行到底的场合；其余是常规场合。"""


__all__ = ["TAKEOVER_SCENES", "TaskScene"]
