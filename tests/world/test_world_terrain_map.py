"""地形格网：精灵分类、隐身槽位与视野裁剪，全部经 `read_terrain` 的公开返回值观测。"""

from __future__ import annotations

from pokemon_agent.world.ram import (
    W_COLLISION_PTR,
    W_CUR_MAP,
    W_CUR_MAP_TILESET,
    W_GRASS_TILE,
    W_NUM_SIGNS,
    W_NUM_WARPS,
    W_SPRITES,
    W_TILEMAP,
    W_X_COORD,
    W_Y_COORD,
    read_terrain,
)
from pokemon_agent.world.terrain_sprites import (
    SPRITE_STRIDE,
    W_MISSABLE_FLAGS,
    W_MISSABLE_LIST,
    W_SPRITE_MAP_X,
    W_SPRITE_MAP_Y,
)

SCREEN_COLS, SCREEN_ROWS = 20, 18
COLLISION_LIST = 0xD800
EMPTY_ROW = ".........."
"""9 行格网的一行：全可通行、无任何标记。"""

VISIBLE = {1: (17, 12), 2: (18, 12), 3: (15, 10), 4: (22, 12), 5: (9, 9)}
ORIGINAL = {1: (17, 12), 2: (18, 12), 3: (10, 12), 4: (22, 12), 5: (9, 9)}
"""精灵槽 → C2 表里的原始 x/y（`sprite_position` 会减 4）。"""


class Mem:
    """字典式内存：未写地址读 0，同时支持整数与切片。"""

    def __init__(self, values: dict[int, int]) -> None:
        self._values = dict(values)

    def __getitem__(self, key: int | slice) -> int | bytes:
        if isinstance(key, slice):
            return bytes(self._values.get(address, 0) for address in range(key.start, key.stop))
        return self._values.get(key, 0)


def _memory(coords: dict[int, tuple[int, int]], hidden_slot: int | None = None) -> Mem:
    """碰撞表 `01 05 2C FF`、tilemap 全 `01`、五槽精灵；可选用位图 bit0 隐藏一个槽。"""
    values = {
        W_COLLISION_PTR: COLLISION_LIST & 0xFF,
        W_COLLISION_PTR + 1: COLLISION_LIST >> 8,
        COLLISION_LIST: 0x01,
        COLLISION_LIST + 1: 0x05,
        COLLISION_LIST + 2: 0x2C,
        COLLISION_LIST + 3: 0xFF,
        W_CUR_MAP: 12,
        W_CUR_MAP_TILESET: 0,
        W_GRASS_TILE: 0xFF,
        W_NUM_SIGNS: 0,
        W_NUM_WARPS: 0,
        W_X_COORD: 13,
        W_Y_COORD: 8,
    }
    values.update({W_TILEMAP + i: 0x01 for i in range(SCREEN_COLS * SCREEN_ROWS)})
    for slot, (x, y) in coords.items():
        values[W_SPRITE_MAP_X + SPRITE_STRIDE * slot] = x
        values[W_SPRITE_MAP_Y + SPRITE_STRIDE * slot] = y
    values[W_SPRITES + SPRITE_STRIDE] = 0x01  # 槽1：人形
    values[W_SPRITES + SPRITE_STRIDE * 2] = 0x3D  # 槽2：宝可梦球
    values[W_SPRITES + SPRITE_STRIDE * 3] = 0x3F  # 槽3：巨石
    values[W_SPRITES + SPRITE_STRIDE * 4] = 0x44  # 槽4：表外静止精灵
    values[W_SPRITES + SPRITE_STRIDE * 5] = 0x00  # 槽5：空槽
    if hidden_slot is not None:
        values[W_MISSABLE_LIST] = hidden_slot
        values[W_MISSABLE_LIST + 1] = 0
        values[W_MISSABLE_LIST + 2] = 0xFF
        values[W_MISSABLE_FLAGS] = 0x01
    return Mem(values)


def _grid(**rows: str) -> list[str]:
    """九行格网：`r2=` 这类关键字指定某一行，其余全空。"""
    filled = dict(rows)
    return [filled.get(f"r{index}", EMPTY_ROW) for index in range(9)]


def test_terrain_places_visible_sprite_kinds() -> None:
    terrain = read_terrain(_memory(VISIBLE))

    assert terrain.cells == _grid(r2="..B.......", r4="....NI...N")
    assert (terrain.map_id, terrain.player_x, terrain.player_y) == (12, 13, 8)


def test_terrain_omits_hidden_sprite_slots() -> None:
    terrain = read_terrain(_memory(ORIGINAL, hidden_slot=1))

    assert terrain.cells == _grid(r4=".....I...N")


def test_terrain_clips_sprites_outside_the_view() -> None:
    terrain = read_terrain(_memory(ORIGINAL))

    assert terrain.cells == _grid(r4="....NI...N")
