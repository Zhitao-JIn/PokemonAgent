"""单次 walk_to 的滚动地形图与 BFS；未知区域只通过可达视野边界逐步探索。"""

from __future__ import annotations

from collections import deque

from ..interface import PLAYER_CELL, TerrainMap

Coordinate = tuple[int, int]
MOVES = (("right", 1, 0), ("down", 0, 1), ("left", -1, 0), ("up", 0, -1))
LEDGES = (("down", "v"), ("left", "<"), ("right", ">"))


class WalkingMap:
    """只在一次脚本调用中保留观测及失败边；不保存跨调用状态。"""

    def __init__(self) -> None:
        self.cells: dict[Coordinate, str] = {}
        self.blocked: set[tuple[Coordinate, str]] = set()

    def observe(self, terrain: TerrainMap) -> None:
        """合并本帧地形，用新观测覆盖旧 NPC/地形；玩家位置始终可站立。"""
        column, row = PLAYER_CELL
        for y, line in enumerate(terrain.cells):
            for x, cell in enumerate(line):
                point = (terrain.player_x + x - column, terrain.player_y + y - row)
                self.cells[point] = cell
        self.cells[terrain.player_x, terrain.player_y] = "."

    def next_button(self, start: Coordinate, target: Coordinate) -> str | None:
        """返回已知最短路的第一键；路径未知时走向可达探索边界。

        目标已观测为障碍或所有已知可达区域均无出口时返回 None。
        前置条件：调用方已合并当前位置的地形；start 不等于 target。
        """
        assert start in self.cells and start != target
        if target in self.cells and self.cells[target] not in ".G@D":
            return None
        routes: dict[Coordinate, tuple[str, int]] = {start: ("", 0)}
        queue = deque([start])
        frontiers: list[Coordinate] = []
        while queue:
            here = queue.popleft()
            if here == target:
                return routes[here][0]
            if self._frontier(here):
                frontiers.append(here)
            for button, point in self._neighbors(here, target):
                if point not in routes:
                    first, distance = routes[here]
                    routes[point] = (first or button, distance + 1)
                    queue.append(point)
        if not frontiers:
            return None
        best = min(
            frontiers,
            key=lambda point: (
                abs(point[0] - target[0]) + abs(point[1] - target[1]) + routes[point][1],
                routes[point][1],
            ),
        )
        return routes[best][0] or None

    def _frontier(self, point: Coordinate) -> bool:
        """已知可走区域是否紧邻尚未观测的格子。"""
        x, y = point
        return any((x + dx, y + dy) not in self.cells for _, dx, dy in MOVES)

    def _neighbors(self, here: Coordinate, target: Coordinate) -> list[tuple[str, Coordinate]]:
        """可行的有向移动；台阶只沿箭头越过一格，门只允许作为终点。"""
        neighbors: list[tuple[str, Coordinate]] = []
        for button, dx, dy in MOVES:
            if (here, button) in self.blocked:
                continue
            point = (here[0] + dx, here[1] + dy)
            cell = self.cells.get(point)
            if (button, cell) in LEDGES:
                point = (point[0] + dx, point[1] + dy)
                cell = self.cells.get(point)
            if cell in (".", "G", "@") or (point == target and cell == "D"):
                neighbors.append((button, point))
        return neighbors
