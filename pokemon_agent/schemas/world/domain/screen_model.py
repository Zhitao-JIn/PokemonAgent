"""地形模型：格子常量、地形符号表。

`Scene`/`Overlay`/`OVERLAY_ACTIONS` 原来在这个文件——它们搬到了
`world/interface/domain/facts.py`，变成 `Facts.Scene`/`Facts.Overlay`
（内部类，`OVERLAY_ACTIONS` 仍是模块级常量，只是键的类型改了）。这里剩下的是
纯地形/网格常量，跟"世界事实长什么样"（`Facts`）不是同一个关注点，不该
挤在一个模型协议子系统的文件里。
"""

from __future__ import annotations

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

DOOR, SIGN, PERSON, ITEM, BOULDER, GRASS = "D", "S", "N", "I", "B", "G"
"""`ITEM`/`BOULDER` 来自精灵表的图片 id 分类（见 `world/ram.py::_sprite_kind`），
不是新读了什么内存——精灵表本来就在读，只是原来只分「人」一类，现在按
pokered 反汇编的 `SPRITE_CONSTANTS`（$3D 起是静止精灵）再细分。"""

TERRAIN_MEANING: dict[str, str] = {
    ".": "能走",
    "G": "草丛，能走，走进去会遇野生宝可梦",
    "D": "门 / 入口 / 楼梯，走进去会切换到另一张地图",
    "S": "招牌或可调查物，走不过去；面朝它按 A 可以看",
    "N": "人，走不过去；面朝它按 A 可以对话",
    "I": "地上的物品，走进去会自动拾取（不用按 A）",
    "B": "巨石，走不过去；需要学会「怪力」才能推动，这一版不做推动判定",
    "#": "墙 / 树 / 建筑 / 水面，走不过去",
    "@": "你自己。图上标 @ 的那一格就是 `where` 那一行给的坐标",
}
"""地形符号的含义。**每一个都来自模拟器内存，没有一个是认出来的。**

    .  #   ← tile id 查 tileset 的可通行表（游戏自己的 CheckTilePassable）
    G      ← tileset 头里的 wGrassTile
    D      ← 地图头的 warp 表（还带着通往哪张地图）
    S      ← 地图头的 sign 表
    N/I/B  ← 精灵表 wSpriteStateData1，按图片 id 分「人 / 物 / 石」三类
             （分界见 `world/ram.py::_sprite_kind`，数值来自 pokered 反汇编）
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
