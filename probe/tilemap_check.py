"""直接从模拟器读地形 —— **只读，不碰主流程**。

    python -m probe.tilemap_check              # 读当前存档
    python -m probe.tilemap_check up 2         # 读完之后按 2 次 up，再读一遍

## 为什么走这条路

视觉模型试了三轮（方向字段 → 通行性二值 → 语义符号），仍然把墙认成门、
把窗户认成人。每轮换的都是**问法**，答案一样，说明瓶颈不在问法。

而这些信息游戏自己一直有：它每一步都要判断"前面那格能不能走"，判断依据就在内存里。

## 地址与判定逻辑（来自 pret/pokered 与 DataCrystal，见文末）

    wTileMap             C3A0-C507   屏幕上 20x18 个 tile 的 id，**已经是屏幕坐标，
                                     不用管 SCX/SCY 滚动**
    wCurMap              D35E        当前地图编号
    wYCoord / wXCoord    D361/D362   主角在地图里的格子坐标
    wCurMapTileset       D367        当前 tileset
    wTilesetBank         D52B        tileset 数据所在的 ROM bank
    wTilesetCollisionPtr D530-D531   指向"可通行 tile 列表"，$FF 结尾

游戏自己的碰撞判定（`CheckTilePassable`）就是：取目标格的 tile id，
在那张表里线性查找，命中 = 能走，查到 $FF = 撞墙。**我们照抄这一段即可**，
不需要任何识别。

## 这个脚本要回答的问题

1. **读出来的通行图和画面对得上吗。** 对得上，几何这一维就从 87% 变成 100%。
2. **一个 16x16 格子里的 4 个 8x8 tile，通行性一致吗。** 一致的话取哪个都行；
   不一致就得先搞清楚游戏按哪个判，别自作主张取平均。
3. **主角在 wTileMap 的哪个位置。** 我们那套 10x9 网格认定主角在 (4,4)，
   对应 wTileMap 的第 8-9 列、第 8-9 行——**要验证，不要假设**。

跑完把输出贴回来。

Sources:
- https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map
- https://github.com/pret/pokered/blob/master/ram/wram.asm
- https://github.com/pret/pokered/blob/master/home/overworld.asm
"""

from __future__ import annotations

import sys

from pyboy import PyBoy

ROM = "assets/rom"
STATE = "assets/rom.state"

W_TILEMAP = 0xC3A0
SCREEN_COLS, SCREEN_ROWS = 20, 18

W_CUR_MAP = 0xD35E
W_Y_COORD, W_X_COORD = 0xD361, 0xD362
W_TILESET = 0xD367
W_TILESET_BANK = 0xD52B
W_COLLISION_PTR = 0xD530

PLAYER_TILE = (8, 8)
"""主角在 wTileMap 里的 (列, 行)。

来自 28 张截图的观测：我们那套 16x16 网格里主角恒在 (4,4)，
换算成 8x8 tile 就是第 8-9 列、第 8-9 行。**这是待验证的假设**，
脚本会把它标在图上，对不上就说明换算错了。
"""


def read_passable(pyboy: PyBoy) -> set[int]:
    """读出当前 tileset 的可通行 tile 列表。

    抄的是游戏自己的 `CheckTilePassable`：解引用 `wTilesetCollisionPtr`，
    在对应 ROM bank 里一路读到 `$FF`。

    **不解释、不推断、不识别** —— 这张表就是游戏判定的依据本身。
    """
    lo, hi = pyboy.memory[W_COLLISION_PTR], pyboy.memory[W_COLLISION_PTR + 1]
    addr = (hi << 8) | lo

    # **表在 bank 0，不在 wTilesetBank。** 指针落在 0x0000-0x3FFF，也就是常驻的
    # home bank；`wTilesetBank`（=25）管的是 blocks/gfx 数据，和这张表无关。
    # 游戏自己也没为它切 bank（`CheckTilePassable` 直接 `ld a, [hli]`），
    # 我第一版照着 wTilesetBank 读，读出来是别的数据段的 2 个字节——
    # **不报错，只是安静地给了一张错的表**。
    out: set[int] = set()
    for i in range(256):                       # 上限只是防呆，正常表只有几十项
        b = pyboy.memory[addr + i]
        if b == 0xFF:
            break
        out.add(b)
    print(f"tileset={pyboy.memory[W_TILESET]}  "
          f"collision_ptr=0x{addr:04X}  可通行 tile {len(out)} 种")
    print("  " + " ".join(f"{t:02X}" for t in sorted(out)))
    return out


def read_screen_tiles(pyboy: PyBoy) -> list[list[int]]:
    """屏幕上 20x18 个 tile 的 id。**已经是屏幕坐标**，不需要处理滚动。"""
    raw = pyboy.memory[W_TILEMAP:W_TILEMAP + SCREEN_COLS * SCREEN_ROWS]
    return [list(raw[r * SCREEN_COLS:(r + 1) * SCREEN_COLS]) for r in range(SCREEN_ROWS)]


def show(pyboy: PyBoy, label: str) -> None:
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
    print(f"map={pyboy.memory[W_CUR_MAP]}  "
          f"player=(x={pyboy.memory[W_X_COORD]}, y={pyboy.memory[W_Y_COORD]})")

    passable = read_passable(pyboy)
    tiles = read_screen_tiles(pyboy)

    print("\n--- 20x18 tile id ---")
    print("     " + " ".join(f"{c:>2}" for c in range(SCREEN_COLS)))
    for r, row in enumerate(tiles):
        print(f" {r:>2}  " + " ".join(f"{t:02X}" for t in row))

    print("\n--- 20x18 通行性（. 能走 / # 不能）---")
    for r, row in enumerate(tiles):
        line = "".join("." if t in passable else "#" for t in row)
        print(f" {r:>2}  {line}")

    # 10x9 的格子：每格 2x2 个 tile。四个子 tile 通行性是否一致，是个关键统计——
    # 一致就随便取一个，不一致说明游戏按某个特定子格判，得先搞清楚再取。
    print("\n--- 10x9 格子（@ 是我们假设的主角位置）---")
    disagree = 0
    for r in range(9):
        line = ""
        for c in range(10):
            quad = [tiles[2 * r + dr][2 * c + dc] for dr in (0, 1) for dc in (0, 1)]
            ok = [t in passable for t in quad]
            if len(set(ok)) > 1:
                disagree += 1
                ch = "~"                       # 四个子格意见不一
            else:
                ch = "." if ok[0] else "#"
            if (2 * c, 2 * r) == PLAYER_TILE:
                ch = "@"
            line += ch
        print(f" {r}   {line}")
    print(f"\n四个子 tile 通行性不一致的格子: {disagree}/90"
          f"{'   <-- 全一致，取哪个都行' if disagree == 0 else '   <-- 需要确认游戏按哪个子格判'}")


def main() -> None:
    press = sys.argv[1] if len(sys.argv) > 1 else ""
    times = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    pyboy = PyBoy(ROM, window="null")
    with open(STATE, "rb") as f:
        pyboy.load_state(f)
    pyboy.tick(1)

    show(pyboy, "移动前")

    if press:
        for _ in range(times):
            pyboy.button(press, delay=10)
            for _ in range(60):
                pyboy.tick(1)
        for _ in range(120):
            pyboy.tick(1)
        show(pyboy, f"按了 {times} 次 {press} 之后")

    pyboy.stop()


if __name__ == "__main__":
    main()
