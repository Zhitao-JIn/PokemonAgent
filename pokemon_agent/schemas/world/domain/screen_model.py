"""屏幕与地形模型：场合、叠加层、动作掩码表、格子常量、地形符号表。"""

from __future__ import annotations

from enum import Enum


class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"  # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"  # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"  # 战斗中
    MENU = "menu"  # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
    SHOP = "shop"  # 商店买卖界面
    TRANSITION = "transition"  # 过场：黑屏、进出门、白闪


class Overlay(str, Enum):
    """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

    NONE = "none"  # 没有弹出层，直接操作角色
    DIALOG = "dialog"  # 对话框：一段文本等你推进
    CHOICE = "choice"  # 选择框：一组选项 + 光标


# ---- 两张表：二元组的收益就兑现在这里 ----

OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]] = {
    Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Overlay.DIALOG: ("a",),  # 方向键无效，只能推进
    # 掩码取**并集**而不是交集：`choice` 底下盖着两种物理布局——商店/对话的
    # yes-no 是竖排，战斗行动菜单是 2×2（FIGHT PKMN / ITEM RUN），
    # 任取交集都会让某种布局的按键物理上够不着。
    # **给不出正确的键，换来的不是大脑不动，是它编一个能解释掩码的世界模型。**
    # 代价是竖排选择框里左右成了空按键（按下去画面不变，白费一步）——
    # 这个代价可见（记忆里前后两份快照摆在一起，字段一模一样），
    # 而够不着的选项不可见。
    Overlay.CHOICE: ("up", "down", "left", "right", "a", "b"),
}
"""动作掩码**只看 overlay**，与 scene 无关。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。

代价在 `CHOICE` 上付：它盖着的两种布局按键需求不同，掩码取的是**并集**而不是
交集——宁可多给两个当帧无效的键，也不能少给一个够得着某个选项的键。
真要按 scene 收窄，就得把这张表的键从 `Overlay` 改成 `(Scene, Overlay)`，
`BUTTON_HELP` 跟着一起改；那是另一笔账，不在这条注释解决。
"""

GRID_COLS, GRID_ROWS = 10, 9
"""屏幕上有几列几行格子。160/16 = 10，144/16 = 9。"""

PLAYER_CELL = (4, 4)
"""主角在屏幕上的格子坐标 `(col, row)`，**是个常量**。

宝可梦红的镜头锁死在主角身上，所以他在屏幕上的位置永远不变——28 张真实截图
（野外、室内、有无对话框）无一例外。

这一条把感知任务降了一个维度：**模型不需要定位主角**，只需要读格子内容。
它同时提供一个免费的自检位——模型把 `@` 放到别处，说明它的坐标系整个是错的，
这一帧判废重试，不必等 agent 撞墙才发现。
"""

PLAYER_MARK = "@"

DOOR, SIGN, PERSON, GRASS = "D", "S", "N", "G"

TERRAIN_MEANING: dict[str, str] = {
    ".": "能走",
    "G": "草丛，能走，走进去会遇野生宝可梦",
    "D": "门 / 入口 / 楼梯，走进去会切换到另一张地图",
    "S": "招牌或可调查物，走不过去；面朝它按 A 可以看",
    "N": "人，走不过去；面朝它按 A 可以对话",
    "#": "墙 / 树 / 建筑 / 水面，走不过去",
    "@": "你自己。图上标 @ 的那一格就是 `where` 那一行给的坐标",
}
"""地形符号的含义。**每一个都来自模拟器内存，没有一个是认出来的。**

    .  #   ← tile id 查 tileset 的可通行表（游戏自己的 CheckTilePassable）
    G      ← tileset 头里的 wGrassTile
    D      ← 地图头的 warp 表（还带着通往哪张地图）
    S      ← 地图头的 sign 表
    N      ← 精灵表 wSpriteStateData1
    @      ← 常量，镜头锁在主角身上

这就是这一版和前三版的根本差别：视觉模型反复读错的东西（墙认成门、窗户认成人），
在这里**根本不存在"认"这个动作**。

这份 dict 同时是 prompt 里的图例来源（`terrain_legend()`），两边共用一份——
各写一份必然漂移，而模型和大脑用两套字典这种错不会报错，只会静默互相误解。
"""

MAP_CHARS = frozenset(TERRAIN_MEANING)


def terrain_legend() -> str:
    """渲染成 prompt 和动作说明里的图例。"""
    return "\n".join(f"- `{ch}` {text}" for ch, text in TERRAIN_MEANING.items())


# ---- 动作契约的跨模块常量（原 tools 包） ----
