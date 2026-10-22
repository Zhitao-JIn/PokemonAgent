"""评测自有的「真值文本格式」：`where` / `walk_map` / `neighbors` 三行文本。

**为什么评测侧要自己留一份**（决定 H，2026-10-22）：解码比对的真值文件是冻结的
**文本**，文件不改，所以解码侧不能改成比结构。世界子系统里那三个 `render` 方法
（`PlaceInWorld.render` / `TerrainMap.render` / `TerrainMap.render_neighbors`）是
prompt 模块的渲染方言，随 CP6 一并退场；评测要的只是"当年写进真值的那三行
长什么样"，因此把它复制成评测自有的格式定义。

`tests/evals/test_decode_terrain_text.py` 用全量真值帧证明这份复制与 world 方法
逐字节相等——相等之后，world 里的那份才能删。
"""

from __future__ import annotations

from pokemon_agent.world import PlaceInWorld, TerrainMap
from pokemon_agent.world.interface.domain.screen_model import (
    GRID_COLS,
    GRID_ROWS,
    PLAYER_CELL,
    PLAYER_MARK,
)


def render_where(place: PlaceInWorld) -> str:
    """`PlaceInWorld.render()` 的评测副本：全局坐标一行。"""
    return f"全局坐标 地图{place.map_id} x={place.x} y={place.y}"


def render_walk_map(terrain: TerrainMap) -> str:
    """`TerrainMap.render()` 的评测副本：带行列号的整屏文本。"""
    col, row = PLAYER_CELL
    ys = [terrain.player_y + r - row for r in range(GRID_ROWS)]
    left, right = terrain.player_x - col, terrain.player_x + GRID_COLS - 1 - col
    gutter = max(len(str(y)) for y in ys)

    lines = [f"这一屏 {GRID_COLS} 列 × {GRID_ROWS} 行；每行末尾括号里是该行首尾两格的全局 x"]
    for r, line in enumerate(terrain.cells):
        chars = list(line)
        if r == row:
            chars[col] = PLAYER_MARK
        lines.append(f"y={ys[r]:<{gutter}} " + "".join(chars) + f"  (x={left}..{right})")
    return "\n".join(lines)


def render_neighbors(terrain: TerrainMap) -> str:
    """`TerrainMap.render_neighbors()` 的评测副本：四邻一行。"""
    col, row = PLAYER_CELL
    neighbor = {
        "up": terrain.cells[row - 1][col],
        "down": terrain.cells[row + 1][col],
        "left": terrain.cells[row][col - 1],
        "right": terrain.cells[row][col + 1],
    }
    names = {"up": "北", "down": "南", "left": "西", "right": "东"}
    return " ".join(f"{names[d]} {neighbor[d]}" for d in ("up", "down", "left", "right"))
