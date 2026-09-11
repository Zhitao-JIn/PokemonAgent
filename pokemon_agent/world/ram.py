"""直接读模拟器内存：坐标、地图编号、地形通行图、门与招牌的位置。

**这些是确定的，不会读错。** 视觉模型看得懂"屏幕上有一扇门"，但说不准它在哪一格；
RAM 说得准。所以凡是 RAM 能回答的，都不问模型——省钱是次要的，主要是省掉一整类
读错。两边的分工写在 `pyboy_world.py` 的模块 docstring 里。

代价是**这一层和游戏版本强绑定**：里面每个地址常量都是《宝可梦 红》的。
换版本要重来一遍，而且读错地址不会报错，只会给出一张看起来合理的错地图——
所以这里的函数都尽量做到"读出来的东西自带可核对的结构"（比如地形图的形状固定
10×9，越界的门和招牌静默丢弃而不是画到别处）。

**这个文件只留"怎么读"。** "读出来是什么形状"的两份定义——`Memory`（一个
Protocol，只要求能按地址取字节）和 `TerrainMap`（`read_terrain` 的产出
schema）——都搬到了 `interface/`（`memory.py` + `domain/terrain_map.py`），
这里只 `from .interface import Memory, TerrainMap` 拿来用。
"""

from __future__ import annotations

from .interface import Facts, Memory, TerrainMap
from .interface.domain import (
    BOULDER,
    DOOR,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    ITEM,
    PERSON,
    PLAYER_CELL,
    SIGN,
)

W_TILEMAP = 0xC3A0
"""屏幕上 20x18 个 tile 的 id。

**已经是屏幕坐标**——这是游戏自己维护的"当前画面"缓冲区，不需要处理 SCX/SCY 滚动，
也不会截到滚动中途的半格。用它比读 PPU 的背景层省掉一整类对齐问题。
"""

SCREEN_COLS, SCREEN_ROWS = 20, 18

W_CUR_MAP = 0xD35E
W_Y_COORD, W_X_COORD = 0xD361, 0xD362
W_COLLISION_PTR = 0xD530
W_GRASS_TILE = 0xD535

W_NUM_WARPS = 0xD3AE
"""门的数量，后面跟着 N 条 `(y, x, 目标 warp, 目标地图)`。

**实测确认**：真新镇读出 3 条，目标是 map 37 / 39 / 40 ——
自己家、小茂家、大木研究所，坐标也和画面对得上。
"""

W_NUM_SIGNS = 0xD4B0
"""招牌的数量，后面跟着 N 条 `(y, x)`。

**实测确认**：真新镇读出 4 条，其中 `(y=5, x=11)` 换算到屏幕正是画面里那块招牌。
"""

W_SPRITES = 0xC100
SPRITE_STRIDE = 16
"""精灵表。每个精灵 16 字节，我们只用四个偏移：

    +0  图片 id（0 = 这个槽位空着）
    +4  屏幕 y 像素
    +6  屏幕 x 像素
    +9  朝向（0 下 / 4 上 / 8 左 / C 右）

0 号槽位是**主角自己**。实测他的 `(x=64, y=60)` 换算过来正好是格子 (4,4)——
y 差的那 4 像素是贴图偏移，这也顺带验证了换算公式。
"""

FACING_BY_BYTE: dict[int, str] = {0: "south", 4: "north", 8: "west", 12: "east"}
"""精灵表 +9 那个字节 → 朝向。取值和 `BUTTON_FACING` 的是同一套词，
因为工具层要拿"这一步按的方向"和"现在面朝的方向"直接比。
"""

FIRST_STILL_SPRITE = 0x3D
"""精灵图片 id（`+0` 字节）的分界：**小于它是会走动的人形**（NPC / 训练师），
**大于等于它是静止的场景物件**（球、化石、巨石……）。数值和下面这张表都来自
pokered 反汇编的精灵常量表（`SPRITE_POKE_BALL` 排在这条线的第一个，$3D）：
https://github.com/pret/pokered/blob/master/constants/sprite_constants.asm

红/蓝里图片 id 到 0x48（`SPRITE_GAMBLER_ASLEEP`）为止，没有更大的值。
"""

_STILL_SPRITE_KIND: dict[int, str] = {
    0x3D: ITEM,  # SPRITE_POKE_BALL：宝可梦球图标，走进去自动拾取
    0x3E: ITEM,  # SPRITE_FOSSIL：化石
    0x3F: BOULDER,  # SPRITE_BOULDER：巨石，需要"怪力"才能推动
    0x40: ITEM,  # SPRITE_PAPER：告示/便签一类的静止可读物
    0x41: ITEM,  # SPRITE_POKEDEX：图鉴（大木研究所开场剧情用）
    0x42: ITEM,  # SPRITE_CLIPBOARD：写字板（撒法瑞乐园入口签到用）
    0x43: PERSON,  # SPRITE_SNORLAX：卡比兽，挡路且按 A 触发战斗，当"人"处理
    0x45: ITEM,  # SPRITE_OLD_AMBER：化石翼龙
    0x48: PERSON,  # SPRITE_GAMBLER_ASLEEP：睡着的杂鱼，按 A 会对话，当"人"处理
}
"""静止精灵（id ≥ `FIRST_STILL_SPRITE`）按具体 id 分派 kind。

**0x40/0x41/0x42 三个是不确定项**——它们各自绑在某一张地图的具体剧情脚本上
（图鉴只在大木研究所开局出现一次；写字板只在撒法瑞乐园入口），红版反汇编里
没有查到"走上去/按 A 之后到底是消失还是留着"这类脚本细节，先按"物"记，
真遇到那一格时按 `harness/object_interactions.py::kind_in_frame` 判出来的实测结果校正（同 `SUB_TILE` 定下来的方法）。

保底策略写在 `_sprite_kind` 里，不在这张表：不认识的 id 归 `PERSON` 而不是
`ITEM`——把巨石当成能捡的东西，产出的交互事件会把后面的判断带偏；
错当成"人"，最多是一次白问的对话尝试，没有下游副作用。
"""


def _sprite_kind(pic_id: int) -> str:
    """精灵图片 id → 地图符号（`PERSON`/`ITEM`/`BOULDER` 之一）。

    前置条件：`pic_id` 非 0（空槽位由调用方在读之前就跳过了）。
    """
    if pic_id < FIRST_STILL_SPRITE:
        return PERSON
    return _STILL_SPRITE_KIND.get(pic_id, PERSON)


def read_facing(mem: Memory) -> str:
    """主角面朝哪边。**读的是游戏自己的状态，不是从我们按过的键推的。**

    不用按键推的理由：开局和过场之后朝向未知（没按过键），而且朝向不进存档，
    checkpoint 恢复不回来——`docs/spec/harness/SPEC.md` 1.4 记着这个洞。

    后置条件：返回 `BUTTON_FACING` 的四个值之一，或空串（读到的不是已知值）。

    读出主角当前朝向。
    """
    return FACING_BY_BYTE.get(int(mem[W_SPRITES + 9]), "")


SUB_TILE = (0, 1)
"""一个 16x16 格子里，拿哪个 8x8 子 tile 去查通行表。`(dc, dr)` = 左下。

**这是实测定出来的，不是猜的。** 90 个格子里只有一个四子格意见不一致——
右边那栋房子的门：左上 `0x0B`、右上 `0x0C`、右下 `0x1C` 都不可通行，
只有左下 `0x1B` 可通行。取左下，门就是能进的，与画面一致。

这也符合直觉：碰撞判的是**脚下那一格**，而角色贴图的脚在格子下半部。
样本只有一个歧义格，所以这条是"当前证据支持"，不是"已证明"——
真正的判据是 `_ambiguous`：它数出还有多少格子存在歧义，一旦这个数涨起来，
就说明这条采样规则不够用了，得回去看游戏是怎么算的。
"""


def read_passable(mem: Memory) -> set[int]:
    """当前 tileset 的可通行 tile 集合。

    后置条件：非空。空集合意味着满屏都走不了，那只可能是读错了地址，
        不可能是游戏的真实状态。

    **表在 bank 0，不在 `wTilesetBank`。** 指针落在 0x0000-0x3FFF，也就是常驻的
    home bank；`wTilesetBank` 管的是 blocks/gfx 数据。游戏自己也没为它切 bank
    （`CheckTilePassable` 直接 `ld a, [hli]`）。
    我第一版照着 `wTilesetBank` 读，得到的是别的数据段的两个字节——
    **不报错，只是安静地给了一张错的表，然后整屏都变成"不可通行"**。

    取当前 tileset 里可以走的 tile 编号。
    """
    lo, hi = mem[W_COLLISION_PTR], mem[W_COLLISION_PTR + 1]
    addr = (hi << 8) | lo

    out: set[int] = set()
    for i in range(256):  # 上限只是防呆；真实的表只有几十项
        b = mem[addr + i]
        if b == 0xFF:
            break
        out.add(int(b))

    assert out, f"collision list at 0x{addr:04X} is empty — wrong address, not a real state"
    return out


def read_screen_tiles(mem: Memory) -> list[list[int]]:
    """屏幕上 20x18 个 tile 的 id。

    取屏幕上 20×18 个 tile 的 id。
    """
    raw = mem[W_TILEMAP : W_TILEMAP + SCREEN_COLS * SCREEN_ROWS]
    return [list(raw[r * SCREEN_COLS : (r + 1) * SCREEN_COLS]) for r in range(SCREEN_ROWS)]


def _entries(mem: Memory, addr: int, stride: int, limit: int = 16) -> list[list[int]]:
    """读一张"先一个数量、再 N 条定长记录"的表。红版的 warp / sign 都是这个形状。

    读一张「先一个数量、再 N 条定长记录」的表。
    """
    n = min(int(mem[addr]), limit)
    return [[int(mem[addr + 1 + i * stride + k]) for k in range(stride)] for i in range(n)]


def read_terrain(mem: Memory) -> TerrainMap:
    """读出 10x9 的地形图、主角坐标、地图编号。

    后置条件：`cells` 是 GRID_ROWS 行、每行 GRID_COLS 个字符；主角那格标 `@`。

    ## 语义符号也来自内存，不是认出来的

    通行性只说得出"过不去"，说不出那是墙、是门、是招牌还是人——而后面这些
    红版全都存成了结构化的表：门在 warp 表里（还带着通往哪张地图），
    招牌在 sign 表里，人在精灵表里，草丛的 tile id 写在 tileset 头里。

    所以这里读出来的每一个符号都是**精确**的。视觉模型三轮都读错的东西
    （墙认成门、窗户认成人），在这里根本不存在"认"这个动作。

    读出 10×9 的地形图、主角坐标和地图编号。
    """
    passable = read_passable(mem)
    tiles = read_screen_tiles(mem)
    grass = int(mem[W_GRASS_TILE])
    dc, dr = SUB_TILE

    rows: list[list[str]] = []
    ambiguous = 0
    for r in range(GRID_ROWS):
        line: list[str] = []
        for c in range(GRID_COLS):
            quad = [tiles[2 * r + y][2 * c + x] for y in (0, 1) for x in (0, 1)]
            if len({t in passable for t in quad}) > 1:
                ambiguous += 1
            tile = tiles[2 * r + dr][2 * c + dc]
            if tile == grass:
                line.append(GRASS)
            else:
                line.append("." if tile in passable else "#")
        rows.append(line)

    px, py = int(mem[W_X_COORD]), int(mem[W_Y_COORD])
    pc, pr = PLAYER_CELL

    def place(map_x: int, map_y: int, ch: str) -> None:
        """把地图坐标画到屏幕格子上。**越界的静默丢弃**——地图上的门和招牌
        大多在屏幕外，那不是错误，只是这一帧看不到。

        把地图坐标画到屏幕格子上，越界的丢弃。
        """
        c, r = pc + (map_x - px), pr + (map_y - py)
        if 0 <= c < GRID_COLS and 0 <= r < GRID_ROWS:
            rows[r][c] = ch

    # 顺序 = 优先级，后写的盖前面的：招牌 < 门 < 精灵（人/物/石）。
    # 精灵放最后是因为它会站在门口——那时候"这里有个人"比"这里有扇门"更要紧，
    # 你得先跟他说话或者绕开，门在他身后没有意义；物品/巨石落在门或招牌的格子上
    # 极少见（正常地图不会这么摆），但同一顺序也适用：踩得到的东西比踩不到的更要紧。
    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_SIGNS, 2)]:
        place(x, y, SIGN)
    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_WARPS, 4)]:
        place(x, y, DOOR)
    for i in range(1, 16):  # 0 号是主角自己，跳过
        base = W_SPRITES + i * SPRITE_STRIDE
        pic_id = int(mem[base])
        if pic_id == 0:
            continue
        sx, sy = int(mem[base + 6]), int(mem[base + 4])
        c, r = sx // 16, (sy + 4) // 16
        if 0 <= c < GRID_COLS and 0 <= r < GRID_ROWS:
            rows[r][c] = _sprite_kind(pic_id)

    return TerrainMap(
        cells=["".join(row) for row in rows],
        map_id=int(mem[W_CUR_MAP]),
        player_x=px,
        player_y=py,
        facing=read_facing(mem),
        ambiguous_cells=ambiguous,
    )
