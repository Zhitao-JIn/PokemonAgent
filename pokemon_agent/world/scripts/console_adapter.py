"""`PyBoyWorld` → `WorldConsole` 适配器：脚本层在 server 进程内看模拟器的窗口。

**来源全部现成**：坐标/朝向/场合/现金/背包是 `PyBoyWorld` 与 `ram.py` 已有
能力，这里只做形状对齐，不新增判定；`is_grass` 用 `read_screen_tiles` 的 tile
直读（与 `read_terrain` 同一真源，可判玩家格——`cells` 网格里玩家格被 `@` 盖住，
tile 层没这问题）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..items import item_name
from ..pyboy_world import PRESS_FRAMES
from ..ram import (
    FIRST_STILL_SPRITE,
    GRID_COLS,
    GRID_ROWS,
    PLAYER_CELL,
    SPRITE_STRIDE,
    SUB_TILE,
    W_CUR_MAP,
    W_GRASS_TILE,
    W_SPRITES,
    W_X_COORD,
    W_Y_COORD,
    read_facing,
    read_screen_tiles,
)
from ..readout import read_bag, read_money
from ..scene import classify_scene
from ..screen_text import read_screen_text

if TYPE_CHECKING:
    from ..pyboy_world import PyBoyWorld
    from .engine import ScriptResult

from ..interface import PlaceInWorld, ScreenText, TerrainMap

_INTERACTIVE = ("人", "招牌", "门", "物")


class WorldConsoleAdapter:
    """脚本层的 `WorldConsole` 实现：包住 `PyBoyWorld`，零新判定。"""

    def __init__(self, world: PyBoyWorld) -> None:
        self._w = world
        self._cached_text: ScreenText | None = None

    @property
    def memory(self) -> Any:  # noqa: ANN401 —— Memory 协议按字节下标读
        return self._w._pyboy.memory

    @property
    def rom(self) -> bytes:
        return self._w._rom

    def press(self, key: str) -> None:
        self._cached_text = None
        self._w._pyboy.button(key, delay=PRESS_FRAMES)

    def tick(self, frames: int) -> None:
        self._w._tick(frames)
        if frames:
            self._cached_text = None

    def read(self) -> ScreenText:
        if self._cached_text is None:
            self._cached_text = read_screen_text(self.memory)
        return self._cached_text

    def map_id(self) -> int:
        return int(self.memory[W_CUR_MAP])

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(
            map_id=self.map_id(),
            x=int(self.memory[W_X_COORD]),
            y=int(self.memory[W_Y_COORD]),
        )

    def facing(self) -> str:
        return read_facing(self.memory)

    def terrain(self) -> TerrainMap:
        """读取稳定地图的本帧地形，不执行按键或帧推进。"""
        from ..ram import read_terrain

        return read_terrain(self.memory)

    def is_grass(self, x: int, y: int) -> bool:
        px, py = int(self.memory[W_X_COORD]), int(self.memory[W_Y_COORD])
        pc, pr = PLAYER_CELL
        c, r = x - px + pc, y - py + pr
        if not (0 <= c < GRID_COLS and 0 <= r < GRID_ROWS):
            return False  # 网格外（不可见）不判草——调用方不该问看不见的格子
        tiles = read_screen_tiles(self.memory)
        grass = int(self.memory[W_GRASS_TILE])
        dc, dr = SUB_TILE
        return tiles[2 * r + dr][2 * c + dc] == grass

    def is_npc(self, x: int, y: int) -> bool:
        px, py = int(self.memory[W_X_COORD]), int(self.memory[W_Y_COORD])
        pc, pr = PLAYER_CELL
        for i in range(1, 16):  # 0 号是主角
            base = W_SPRITES + i * SPRITE_STRIDE
            pic_id = int(self.memory[base])
            if pic_id == 0 or pic_id >= FIRST_STILL_SPRITE:
                continue  # 空位 / 静止物件（球、巨石…）不算 NPC
            sx, sy = int(self.memory[base + 6]), int(self.memory[base + 4])
            c, r = sx // 16, (sy + 4) // 16
            if (px + c - pc, py + r - pr) == (x, y):
                return True
        return False

    def object_kind(self, x: int, y: int) -> str | None:
        """返回面前地标的种类，供逐步观察生成 `facing_object`。"""
        from ..ram import read_terrain

        for mark in read_terrain(self.memory).landmarks():
            if mark.place.x == x and mark.place.y == y and mark.kind in _INTERACTIVE:
                return mark.kind
        return None

    def scene(self) -> str:
        return classify_scene(self.read(), self.memory).value

    def money(self) -> int:
        return read_money(self.memory)

    def bag_count(self, item: str) -> int:
        for b in read_bag(self.memory):
            if item_name(b.item_id) == item:
                return b.quantity
        return 0

    def run_script(self, name: str, args: dict[str, str | int]) -> ScriptResult:
        """执行另一条脚本（脚本组合）：按名字交给能力目录的分发表。"""
        from .catalog import run_script_by_name

        return run_script_by_name(self, name, args)


__all__ = ["WorldConsoleAdapter"]
