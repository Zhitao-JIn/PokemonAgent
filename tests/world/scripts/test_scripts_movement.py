"""移动类脚本单测（P4 第一批）：face_direction / walk_to_adjacent / walk_to / circle_walk。

**对得上谁**：PLAN 附录 A 对应行的单测列（FakeConsole）；真机验收列归用户。
`GridConsole` 在一块可编程的格网世界上模拟 Gen1 物理：按键必转向、走不走取决于
目标格可走性（被挡 = 原地转向），草丛格由集合给定，可预设中途遇怪（battle 帧）。
坐标系 = 过图连续坐标（335 结案口径），测试里只需保证**同一段行程内自洽**。
"""

from __future__ import annotations

from _doubles.grid_console import GridConsole

from pokemon_agent.world.scripts.engine import ScriptRun
from pokemon_agent.world.scripts.movement import (
    circle_walk,
    face_direction,
    walk_to,
    walk_to_adjacent,
)

MAP = 12


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
    assert res.data["steps_used"] == 6


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


def test_walk_to_follows_a_detour_that_initially_moves_away_from_target() -> None:
    walkable = _rect(10, 5, 10, 13) | _rect(10, 13, 16, 13) | _rect(16, 5, 16, 13)
    console = GridConsole(walkable, start=(10, 5))

    result = walk_to(console, 16, 5, max_steps=30)

    assert result.ok and result.code == "ok"
    assert (console.x, console.y) == (16, 5)
    assert result.data["steps_used"] == 22


def test_walk_to_stops_at_an_unreachable_target_without_pressing_keys() -> None:
    console = GridConsole(_rect(10, 5, 18, 12) - {(16, 8)}, start=(15, 8))

    result = walk_to(console, 16, 8)

    assert result.code == "blocked"
    assert console.presses == 0


def test_walk_to_stops_and_counts_the_press_that_triggers_battle() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8), battle_at={(16, 8)})

    result = walk_to(console, 18, 8)

    assert result.code == "battle_started"
    assert result.data["steps_used"] == 1
    assert console.presses == 1


def test_walk_to_replans_after_a_collision_missing_from_the_terrain() -> None:
    console = GridConsole(_rect(10, 5, 20, 15), start=(15, 8), hidden_obstacles={(16, 8)})

    result = walk_to(console, 18, 8)

    assert result.ok
    assert (console.x, console.y) == (18, 8)
    assert result.data["steps_used"] == console.presses == 6


def test_walk_to_explores_rolling_terrain_to_a_target_outside_the_initial_view() -> None:
    console = GridConsole(_rect(5, 5, 30, 5), start=(5, 5))

    result = walk_to(console, 30, 5)

    assert result.ok
    assert result.data["steps_used"] == 25


def test_walk_to_jumps_a_ledge_in_its_allowed_direction() -> None:
    console = GridConsole({(5, 5), (5, 7)}, start=(5, 5), ledges={(5, 6): "v"})

    result = walk_to(console, 5, 7)

    assert result.ok
    assert result.data["steps_used"] == 1


def test_walk_to_does_not_jump_a_ledge_in_reverse() -> None:
    console = GridConsole({(5, 5), (5, 7)}, start=(5, 7), ledges={(5, 6): "v"})

    result = walk_to(console, 5, 5)

    assert result.code == "blocked"
    assert console.presses == 0


def test_walk_to_stops_on_a_map_transition() -> None:
    console = GridConsole({(5, 5), (6, 5)}, start=(5, 5), warp_at={(6, 5)})

    result = walk_to(console, 6, 5)

    assert result.code == "map_changed"
    assert result.data["map_id"] == MAP + 1
    assert result.data["steps_used"] == 1


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
