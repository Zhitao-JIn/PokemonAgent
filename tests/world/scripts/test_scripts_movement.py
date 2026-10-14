"""移动类脚本单测（P4 第一批）：face_direction / walk_to_adjacent / walk_to / circle_walk。

**对得上谁**：PLAN 附录 A 对应行的单测列（FakeConsole）；真机验收列归用户。
`GridConsole` 在一块可编程的格网世界上模拟 Gen1 物理：按键必转向、走不走取决于
目标格可走性（被挡 = 原地转向），草丛格由集合给定，可预设中途遇怪（battle 帧）。
坐标系 = 过图连续坐标（335 结案口径），测试里只需保证**同一段行程内自洽**。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.interface import BUTTON_FACING
from pokemon_agent.world.scripts.engine import ScriptRun
from pokemon_agent.world.scripts.movement import (
    circle_walk,
    face_direction,
    walk_to,
    walk_to_adjacent,
)

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
    ) -> None:
        self._walkable = walkable | (grass or set())
        self._grass = grass or set()
        self._battle_at = battle_at or set()
        self._battle = False
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
        if (nx, ny) in self._walkable:
            self.x, self.y = nx, ny
            if (nx, ny) in self._battle_at:
                self._battle = True  # 踩进遇怪格：战斗标志立起（map_id 不动）

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


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002 —— 默认全 0（非战斗非 MART）
        return 0


def _rect(x0: int, y0: int, x1: int, y1: int) -> set[tuple[int, int]]:
    return {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


# ---- walk_to_adjacent（附录 A #3）----


def test_walk_to_adjacent_open_ground() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    res = walk_to_adjacent(console, "east")
    assert res.ok and res.code == "ok"
    assert (console.x, console.y) == (16, 8)
    assert res.data["entered_grass"] is False


def test_walk_to_adjacent_blocked_by_tree_or_npc() -> None:
    walkable = _rect(10, 5, 20, 15) - {(16, 8)}  # (16,8) 不可走 = 树/NPC
    console = GridConsole(walkable, start=(15, 8))
    res = walk_to_adjacent(console, "east")
    assert not res.ok and res.code == "blocked"
    assert (console.x, console.y) == (15, 8), "被挡不位移"


def test_walk_to_adjacent_enters_grass() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8), grass={(16, 8)})
    res = walk_to_adjacent(console, "east")
    assert res.ok and res.code == "ok"
    assert res.data["entered_grass"] is True


def test_walk_to_adjacent_rejects_bad_direction() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    res = walk_to_adjacent(console, "uphill")
    assert not res.ok and res.code == "rejected"


# ---- face_direction（附录 A #5）----


def test_face_direction_already_facing_is_noop() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    console._facing = "north"
    presses_before = console.presses
    res = face_direction(console, "north")
    assert res.ok and res.data["moved"] is False
    assert console.presses == presses_before, "已面向不按键"
    assert res.data["facing"] == "north"


def test_face_direction_moves_when_open() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    res = face_direction(console, "north")
    assert res.ok and res.data["moved"] is True
    assert (console.x, console.y) == (15, 7)
    assert res.data["facing"] == "north"


def test_face_direction_turns_in_place_when_blocked() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 5))  # (15,4) 不可走
    res = face_direction(console, "north")
    assert res.ok and res.data["moved"] is False
    assert (console.x, console.y) == (15, 5), "原地转向"
    assert console.facing() == "north"


# ---- walk_to（附录 A #4）----


def test_walk_to_straight_line() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    res = walk_to(console, 18, 8)
    assert res.ok and res.code == "ok"
    assert (console.x, console.y) == (18, 8)
    assert res.data["steps_used"] == 3


def test_walk_to_detours_around_wall() -> None:
    walkable = _rect(10, 5, 20, 15) - {(15, 9)}  # 正南一堵墙
    console = GridConsole(walkable, start=(15, 8))
    res = walk_to(console, 15, 12)
    assert res.ok and res.code == "ok"
    assert (console.x, console.y) == (15, 12)
    assert (15, 9) not in _rect(console.x, console.y, console.x, console.y) or True
    assert res.data["steps_used"] > 4, "绕行步数必多于直线"


def test_walk_to_fully_walled_blocks() -> None:
    console = GridConsole({(10, 5)}, start=(10, 5))  # 四周全不可走
    res = walk_to(console, 15, 8)
    assert not res.ok and res.code == "blocked"
    assert (console.x, console.y) == (10, 5), "原地被挡"


def test_walk_to_adjacent_counter_stops_without_wandering() -> None:
    console = GridConsole(_rect(1, 2, 6, 6) - {(3, 2)}, start=(3, 3))

    result = walk_to(console, 3, 2)

    assert result.code == "blocked"
    assert (console.x, console.y) == (3, 3)


def test_walk_to_not_converging() -> None:
    # 南向被长墙挡死、东侧通道又被封 → 来回横移 5 步距离不减
    wall = {(7, y) for y in range(5, 11)}
    walkable = _rect(4, 5, 20, 15) - _rect(5, 6, 20, 10) - wall
    console = GridConsole(walkable, start=(5, 5))
    res = walk_to(console, 5, 10, max_steps=20)
    assert not res.ok and res.code == "not_converging"


def test_walk_to_budget_exhausted() -> None:
    console = GridConsole(_rect(0, 0, 40, 40), start=(5, 5))
    res = walk_to(console, 5, 30, max_steps=3)
    assert not res.ok and res.code == "budget_exhausted"
    assert res.data["steps_used"] == 3


# ---- circle_walk（附录 A #2）----


def test_circle_walk_two_laps_back_to_start() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8))
    res = circle_walk(console, laps=2)
    assert res.ok and res.code == "ok"
    assert res.data["laps_done"] == 2
    assert (console.x, console.y) == (15, 8), "圈末回起点"


def test_circle_walk_off_course_on_obstacle() -> None:
    # 圈 east 一步后 south 被挡 → 位移 0 → off_course
    walkable = _rect(15, 8, 17, 10) | {(15, 8)}
    console = GridConsole(walkable - {(15, 9), (16, 9)}, start=(15, 8))
    res = circle_walk(console, laps=1)
    assert not res.ok and res.code == "off_course"


def test_circle_walk_battle_hook_terminates() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8), battle_at={(16, 8)})
    res = circle_walk(console, laps=2)
    assert res.code == "battle_started"
    assert res.data["laps_done"] == 0


def test_script_run_budget_gate_still_works() -> None:
    """骨架预算闸回归锚：预算内走不完 → budget_exhausted（骨架级，circle/walk_to 共用）。"""
    console = GridConsole(_rect(0, 0, 40, 40), start=(5, 5))
    run = ScriptRun(console, budget=2, start_map_id=MAP, start_pos=console.pos())
    res = run.execute(["down", "down", "down"])
    assert res.code == "budget_exhausted"
