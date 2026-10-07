"""task 层的场合分类与接管脚本初态判断：纯函数，只读屏幕缓冲解码结果与内存，不调模型。

判别以屏幕缓冲特征为主（列表类内存变量退出界面后会残留），战斗标志、列表指针、地图图块集只在能区分时作旁证；
特征一律按**整词 / 固定位置**匹配，不做子串匹配
（`TOWN` 里含 `OWN`、对话里会出现 `POKéDEX` 这类词）。
规则给读屏数据集 v2（1037 帧）做了预标，待人工核对；
场合词表与初态定义见 `docs/perceive/spec.md` 第三节。
"""

from __future__ import annotations

from .interface import TAKEOVER_SCENES, Memory, ScreenText, TaskScene
from .scene_layout import has_battle_menu_frame, is_transition
from .screen_text import read_tiles

W_IS_IN_BATTLE = 0xD057
W_LIST_POINTER = 0xCF8B
"""`wListPointer`（两字节）：当前列表的数据地址；退出界面后残留，只作旁证。"""
BAG_ITEMS = 0xD31D
"""`wNumBagItems`：`wListPointer` 指向这里 = 列表是背包。"""
W_CUR_MAP_TILESET = 0xD367
MART_TILESET = 2
"""`wCurMapTileset` = MART（常青市商店实测；其它商店未核）。"""

PC_MARKS = ("WITHDRAW", "DEPOSIT", "LOG OFF", "Storage System", "Accessed", "SEE YA!", "BOX No.")
TITLE_MARKS = ("NEW GAME", "CONTINUE")
START_ITEMS = frozenset({"POKéDEX", "POKéMON", "ITEM", "SAVE", "OPTION", "EXIT"})
"""开始菜单框里的整行词条（玩家名那一行不固定，不算）。"""
LEARN_MARKS = (
    "trying to learn",
    "learn more",
    "than 4 moves",
    "Delete an older",
    "move to make room",
    "Which move should",
    "be forgotten",
    "Abandon learning",
)
"""学新招的提示（`trying to learn / can't learn more than 4 moves! / Delete an older /
move to make room / for XX?`，用 RARE CANDY 实测）。"""
BATTLE_ACTIONS = ["FIGHT", "PKMN", "ITEM", "RUN"]


def classify_scene(text: ScreenText, mem: Memory) -> TaskScene:
    """一帧属于哪个场合。

    text：这一帧的屏幕缓冲解码（`screen_text.read_screen_text`）。
    mem：按绝对地址取字节（模拟器内存，或测评里包了一层的 WRAM 快照）。
    """
    screen = text.screen
    flat = screen.replace("▶", " ").replace("▷", " ")
    in_battle = text.in_battle or mem[W_IS_IN_BATTLE] != 0

    # 步骤 0：用完整屏幕布局与地图载入证据识别过场。
    tiles = read_tiles(mem)
    if is_transition(tiles, screen, mem):
        return TaskScene.TRANSITION

    # 步骤 1：不看战斗与否的接管
    if "A B C D E F G H I" in flat or "a b c d e f g h i" in flat:
        return TaskScene.NAMING
    if any(m in flat for m in LEARN_MARKS):
        return TaskScene.LEARN_MOVE

    # 步骤 2：战斗——选单接管，其余常规
    if in_battle:
        if (
            "Bring out which" in flat
            or "Choose a POK" in flat
            or (_party_list(screen) and "Use item on which" not in flat)
        ):
            return TaskScene.BATTLE_SWITCH
        menu = text.has_cursor or "▷" in screen or has_battle_menu_frame(tiles)
        return TaskScene.BATTLE_MENU if menu and text.options != ["YES", "NO"] else TaskScene.BATTLE

    return _field_scene(text, mem)


def _field_scene(text: ScreenText, mem: Memory) -> TaskScene:
    """非战斗的接管场合优先；列表指针只在对应可见菜单出现时使用。"""
    screen = text.screen
    flat, words = screen.replace("▶", " ").replace("▷", " "), _words(screen)

    # 步骤 3：野外的接管
    if "─MONEY─" in screen:
        return TaskScene.SHOP_ITEMS
    if _pc_items(screen) or any(m in screen for m in PC_MARKS) or _pc_home(text):
        return TaskScene.PC
    if any(m in flat for m in TITLE_MARKS):
        return TaskScene.TITLE
    if "Use item on which" in flat:
        return TaskScene.BAG
    if _party_list(screen) or "Choose a POKéMON" in flat:
        return TaskScene.PARTY
    if "TEXT SPEED" in flat or ("CONTENTS" in words and "SEEN" in words):
        return TaskScene.START_MENU  # 选项页也有 CANCEL，列表指针又可能残留在背包上，得先认
    if ("CANCEL" in words or "×" in screen) and _list_pointer(mem) == BAG_ITEMS:
        return TaskScene.BAG
    if _town_map(screen):
        return TaskScene.BAG  # 城镇地图只能从背包里的道具打开

    return _ordinary_scene(text, mem)


def _ordinary_scene(text: ScreenText, mem: Memory) -> TaskScene:
    """非战斗普通场合按能力页、地图、HUD与对话证据确定。"""
    screen, dialog = text.screen, text.dialog_text
    flat, words = screen.replace("▶", " ").replace("▷", " "), _words(screen)

    # 步骤 4：野外的常规
    if {"STATUS/", "TYPE1/"} & words or "EXP POINTS" in flat or _dex_entry(screen):
        return TaskScene.POKEMON_INFO
    if len(START_ITEMS & words) >= 3:
        return TaskScene.START_MENU
    if "NAME/" in flat and "MONEY/" in flat:
        return TaskScene.START_MENU
    if ":L" in screen and "HP:" in screen:
        return TaskScene.BATTLE  # 战斗 HUD 还在但标志已清：战斗结算
    if mem[W_CUR_MAP_TILESET] == MART_TILESET:
        return TaskScene.SHOP
    if text.strict_dialog or dialog:
        return TaskScene.DIALOG
    if not screen:
        return TaskScene.WALK
    return TaskScene.TRANSITION


def at_start(text: ScreenText, scene: TaskScene) -> bool:
    """接管场合是否在接管脚本的初态：本场合的主菜单画着、实心 `▶` 在上面、屏上没有任何空心 `▷`。

    战斗行动菜单要求光标在FIGHT；其他主菜单允许其任一合法选项。
    只看三角不够：战斗的招式列表 / 背包 / 换人列表、PC 的各级菜单都整块盖住上一层，不留 `▷`。
    调用方要先等画面稳定——游戏处理按键时会擦掉 `▶` 重画。
    前置条件：`scene` 是接管场合。
    """
    assert scene in TAKEOVER_SCENES, f"at_start() on a normal scene {scene!r}"
    if not text.has_cursor or "▷" in text.screen:
        return False
    options, screen = text.options, text.screen
    home = {
        TaskScene.NAMING: True,
        TaskScene.SHOP_ITEMS: {"BUY", "SELL", "QUIT"} <= set(options),
        TaskScene.PC: _pc_home(text),
        TaskScene.BAG: not _party_list(screen) and ("CANCEL" in _words(screen) or "×" in screen),
        TaskScene.BATTLE_MENU: options == BATTLE_ACTIONS and text.cursor == "FIGHT",
        TaskScene.BATTLE_SWITCH: _party_list(screen),
        TaskScene.PARTY: _party_list(screen),
        TaskScene.LEARN_MOVE: options == ["YES", "NO"] and "room" in text.dialog_text,
    }
    return home[scene]


def _pc_home(text: ScreenText) -> bool:
    """PC 主菜单：选哪台 PC（`SOMEONE's PC` / `BILL's PC` / `RED's PC` … `LOG OFF`）。"""
    return "LOG OFF" in text.options and any(o.endswith("'s PC") for o in text.options)


def _pc_items(screen: str) -> bool:
    """PC 道具存取：道具菜单整个露着，或道具列表压在菜单上只剩 `│▷WI┌` 残边。"""
    if "WITHDRAW ITEM" in screen:
        return True
    lines = screen.splitlines()
    return len(lines) > 2 and lines[2][1:4] in ("▷WI", " WI") and lines[2][4:5] == "┌"


def _party_list(screen: str) -> bool:
    """队伍列表：第 0 行有 `:L`，第 1 行 `HP:` 靠左（战斗 HUD 的血条在右半屏）。"""
    lines = screen.splitlines()
    return len(lines) > 1 and ":L" in lines[0] and 0 <= lines[1].find("HP:") <= 6


def _words(screen: str) -> set[str]:
    """屏上所有整词（按空白与框线切开，光标去掉）。"""
    for ch in "▶▷│┌┐└┘─·":
        screen = screen.replace(ch, " ")
    return set(screen.split())


def _dex_entry(screen: str) -> bool:
    """图鉴条目页：身高 `HT`、体重 `WT` 与编号 `No.` 同屏。"""
    words = _words(screen)
    return "HT" in words and "WT" in words and "No." in screen


def _town_map(screen: str) -> bool:
    """城镇地图：只有顶上一行地名，其余全是图形。"""
    lines = [line.strip(" ·") for line in screen.splitlines()]
    named = [line for line in lines if any(ch.isalpha() for ch in line)]
    return len(named) == 1 and lines[0] == named[0]


def _list_pointer(mem: Memory) -> int:
    """`wListPointer`（小端两字节）。"""
    return int(mem[W_LIST_POINTER]) | int(mem[W_LIST_POINTER + 1]) << 8  # type: ignore[arg-type]


__all__ = ["at_start", "classify_scene"]
