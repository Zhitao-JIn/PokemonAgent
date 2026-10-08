"""直接读模拟器内存：坐标、地图编号、地形通行图、门与招牌的位置。"""

from __future__ import annotations

from .interface import Memory, TerrainMap
from .interface.domain import (
    BOULDER,
    DOOR,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    ITEM,
    LEDGE_DOWN,
    LEDGE_LEFT,
    LEDGE_RIGHT,
    PERSON,
    PLAYER_CELL,
    SIGN,
)
from .map_tilesets import map_tilesets
from .terrain_sprites import hidden_slots, sprite_position

W_TILEMAP = 0xC3A0
"""屏幕上 20x18 个 tile 的 id。"""

SCREEN_COLS, SCREEN_ROWS = 20, 18

W_BATTLE_MON_NICK = 0xD009
W_BATTLE_MON_HP = 0xD015
W_BATTLE_MON_STATUS = 0xD018
W_BATTLE_MON_LEVEL = 0xD022
W_BATTLE_MON_MAX_HP = 0xD023
W_ENEMY_MON_NICK = 0xCFDA
W_ENEMY_MON_HP = 0xCFE6
W_ENEMY_MON_STATUS = 0xCFE9
W_ENEMY_MON_LEVEL = 0xCFF3
W_ENEMY_MON_MAX_HP = 0xCFF4
"""战斗双方状态框（`wBattleMon*` / `wEnemyMon*`）。"""

NAME_LENGTH = 11
NAME_END = 0x50

W_TOP_MENU_ITEM_X = 0xCC25
W_CURRENT_MENU_ITEM = 0xCC26
W_MAX_MENU_ITEM = 0xCC28
W_PLAYER_MONEY = 0xD347
W_NUM_BAG_ITEMS = 0xD31D
W_BAG_ITEMS = 0xD31E
W_PARTY_COUNT = 0xD163
W_PARTY_SPECIES = 0xD164
W_PARTY_MON1_HP = 0xD16C
PARTY_MON_SIZE = 0x2C
"""菜单光标、BCD 金钱、背包和队伍地址。"""

BAG_CAPACITY = 20
PARTY_CAPACITY = 6
LIST_END = 0xFF

W_CUR_MAP = 0xD35E
W_Y_COORD, W_X_COORD = 0xD361, 0xD362
W_COLLISION_PTR = 0xD530
W_GRASS_TILE = 0xD535
W_CUR_MAP_TILESET = 0xD367
OVERWORLD_TILESET = 0
"""台阶只存在于野外 tileset（pokered `HandleLedges` 开头就判 `wCurMapTileset == OVERWORLD`）。"""

LEDGE_TILES: dict[int, str] = {
    0x36: LEDGE_DOWN,
    0x37: LEDGE_DOWN,
    0x27: LEDGE_LEFT,
    0x0D: LEDGE_RIGHT,
    0x1D: LEDGE_RIGHT,
}
"""野外 tileset 里台阶的 tile id → 能跳的方向（pokered `data/tilesets/ledge_tiles.asm`"""

W_NUM_WARPS = 0xD3AE
"""门的数量，后面跟着 N 条 `(y, x, 目标 warp, 目标地图)`。"""

W_NUM_SIGNS = 0xD4B0
"""招牌的数量，后面跟着 N 条 `(y, x)`。"""

W_SPRITES = 0xC100
SPRITE_STRIDE = 16
"""精灵图片与朝向在 C1xx 表，地图格位由 C2xx 表读取。"""

FACING_BY_BYTE: dict[int, str] = {0: "south", 4: "north", 8: "west", 12: "east"}
"""精灵表 +9 那个字节 → 朝向。取值和 `BUTTON_FACING` 的是同一套词，"""

FIRST_STILL_SPRITE = 0x3D
"""图片编号小于 0x3D 是人形，其余按物件表分派。"""

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
"""静止精灵（id ≥ `FIRST_STILL_SPRITE`）按具体 id 分派 kind。"""


def _sprite_kind(pic_id: int) -> str:
    """精灵图片 id → 地图符号（`PERSON`/`ITEM`/`BOULDER` 之一）。"""
    if pic_id < FIRST_STILL_SPRITE:
        return PERSON
    return _STILL_SPRITE_KIND.get(pic_id, PERSON)


def read_facing(mem: Memory) -> str:
    """主角面朝哪边。**读的是游戏自己的状态，不是从我们按过的键推的。**"""
    return FACING_BY_BYTE.get(int(mem[W_SPRITES + 9]), "")


SUB_TILE = (0, 1)
"""一个 16x16 格子里，拿哪个 8x8 子 tile 去查通行表。`(dc, dr)` = 左下。"""


def read_passable(mem: Memory) -> set[int]:
    """当前 tileset 的可通行 tile 集合。"""
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
    """屏幕上 20x18 个 tile 的 id。"""
    raw = mem[W_TILEMAP : W_TILEMAP + SCREEN_COLS * SCREEN_ROWS]
    return [list(raw[r * SCREEN_COLS : (r + 1) * SCREEN_COLS]) for r in range(SCREEN_ROWS)]


def _entries(mem: Memory, addr: int, stride: int, limit: int = 16) -> list[list[int]]:
    """读一张"先一个数量、再 N 条定长记录"的表。红版的 warp / sign 都是这个形状。"""
    n = min(int(mem[addr]), limit)
    return [[int(mem[addr + 1 + i * stride + k]) for k in range(stride)] for i in range(n)]


def _terrain_cells(mem: Memory) -> tuple[list[list[str]], int]:
    """左下子图块决定通行与草丛；返回格网及四子图块通行分歧数。"""
    passable = read_passable(mem)
    tiles = read_screen_tiles(mem)
    grass = int(mem[W_GRASS_TILE])
    ledges = LEDGE_TILES if int(mem[W_CUR_MAP_TILESET]) == OVERWORLD_TILESET else {}
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
            if grass != 0xFF and tile == grass:
                line.append(GRASS)
            elif tile in ledges:
                line.append(ledges[tile])
            else:
                line.append("." if tile in passable else "#")
        rows.append(line)

    return rows, ambiguous


def map_settled(mem: Memory) -> bool:
    """地图可用当且仅当通行表非零且地图头 tileset 与 WRAM 一致。"""
    loaded = int(mem[W_COLLISION_PTR]) | int(mem[W_COLLISION_PTR + 1]) << 8
    index = int(mem[W_CUR_MAP])
    table = map_tilesets()
    return bool(loaded) and index < len(table) and table[index] == int(mem[W_CUR_MAP_TILESET])


def read_terrain(mem: Memory) -> TerrainMap:
    """读出 10x9 的地形图、主角坐标、地图编号。"""
    rows, ambiguous = _terrain_cells(mem)
    px, py = int(mem[W_X_COORD]), int(mem[W_Y_COORD])
    pc, pr = PLAYER_CELL

    def place(map_x: int, map_y: int, ch: str) -> None:
        """将地图坐标画到屏幕格网，丢弃视野外坐标。"""
        c, r = pc + (map_x - px), pr + (map_y - py)
        if 0 <= c < GRID_COLS and 0 <= r < GRID_ROWS:
            rows[r][c] = ch

    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_SIGNS, 2)]:
        place(x, y, SIGN)
    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_WARPS, 4)]:
        place(x, y, DOOR)
    hidden = hidden_slots(mem)
    for i in range(1, 16):
        base = W_SPRITES + i * SPRITE_STRIDE
        pic_id = int(mem[base])
        if pic_id == 0 or i in hidden:
            continue
        x, y = sprite_position(mem, i)
        place(x, y, _sprite_kind(pic_id))

    return TerrainMap(
        cells=["".join(row) for row in rows],
        map_id=int(mem[W_CUR_MAP]),
        player_x=px,
        player_y=py,
        facing=read_facing(mem),
        ambiguous_cells=ambiguous,
    )
