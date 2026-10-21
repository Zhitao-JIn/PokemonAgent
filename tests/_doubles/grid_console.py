"""移动脚本测试的滚动格网模拟器，覆盖碰撞、台阶、遇敌与换图。"""

from __future__ import annotations

from typing import Any

from _doubles.world_console import grid_terrain
from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.interface import BUTTON_FACING, TerrainMap

MAP = 12


class GridConsole:
    """格网世界：`walkable` 可走格、`grass` 草丛格、`battle_at` 走到即遇怪。"""

    def __init__(
        self,
        walkable: set[tuple[int, int]],
        *,
        start: tuple[int, int],
        grass: set[tuple[int, int]] | None = None,
        battle_at: set[tuple[int, int]] | None = None,
        map_id: int = MAP,
        hidden_obstacles: set[tuple[int, int]] | None = None,
        ledges: dict[tuple[int, int], str] | None = None,
        warp_at: set[tuple[int, int]] | None = None,
    ) -> None:
        self._walkable = walkable | (grass or set())
        self._grass = grass or set()
        self._battle_at = battle_at or set()
        self._battle = False
        self._hidden_obstacles = hidden_obstacles or set()
        self._ledges = ledges or {}
        self._warp_at = warp_at or set()
        self.x, self.y = start
        self._facing = "south"
        self._map_id = map_id
        self.presses = 0
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        self.presses += 1
        self._facing = BUTTON_FACING[key]
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[key]
        nx, ny = self.x + dx, self.y + dy
        if (nx, ny) in self._ledges:
            if self._ledges[nx, ny] != {"down": "v", "left": "<", "right": ">"}.get(key):
                return
            nx, ny = nx + dx, ny + dy
        if (nx, ny) in self._walkable and (nx, ny) not in self._hidden_obstacles:
            self.x, self.y = nx, ny
            if (nx, ny) in self._battle_at:
                self._battle = True  # 踩进遇怪格：战斗标志立起（map_id 不动）
            if (nx, ny) in self._warp_at:
                self._map_id += 1

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        return ScreenText(in_battle=self._battle)  # 战斗帧 → scene=BATTLE → 钩子终止

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:
        return (x, y) in self._grass

    def terrain(self) -> TerrainMap:
        terrain = grid_terrain(self.pos(), self._walkable)
        for (x, y), cell in {**self._ledges, **dict.fromkeys(self._warp_at, "D")}.items():
            column, row = x - self.x + 4, y - self.y + 4
            if 0 <= column < 10 and 0 <= row < 9:
                line = terrain.cells[row]
                terrain.cells[row] = line[:column] + cell + line[column + 1 :]
        return terrain


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002 —— 默认全 0（非战斗非 MART）
        return 0
