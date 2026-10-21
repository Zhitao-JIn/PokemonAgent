"""移动 / 导航类脚本（§7.2）：face_direction / walk_to_adjacent / walk_to / circle_walk。

**坐标系口径（2026-09-29 335 结案）**：`PlaceInWorld` 的 x/y 是 Gen1 的
wXCoord/wYCoord——**过图连续坐标**，不是图内坐标。本层一切比较（曼哈顿距离、
圈末回起点、blocked 判定）都只在**同一段图内行程**上做，跨图语义归
MapChanged 钩子（触发即终止），不做任何图内换算。

**方向词**：脚本入参与返回值统一用朝向词 `north/south/west/east`
（与 `FACING_STEP` / 记忆 / 事件一致）；按键名经 `BUTTON_OF` 换算。
"""

from __future__ import annotations

from typing import Any

from .engine import Halt, ScriptResult, ScriptRun, WorldConsole
from .interruptions import field_policy
from .pathfinding import WalkingMap

DIRECTIONS = ("north", "south", "west", "east")
"""脚本方向参数的合法词表（朝向词，与 `FACING_STEP` 同套）。"""

BUTTON_OF: dict[str, str] = {"north": "up", "south": "down", "west": "left", "east": "right"}
"""朝向词 → 方向键名（与 `world.ram.BUTTON_FACING` 互为反表）。"""

STEP_OF: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "west": (-1, 0),
    "east": (1, 0),
}
"""朝向词 → 位移（与 `FACING_STEP` 同值；本地一份避免跨层 import）。"""


def _reject(direction: str) -> ScriptResult:
    return ScriptResult(ok=False, code="rejected", data={"direction": direction})


def _run(console: WorldConsole, budget: int) -> ScriptRun:
    return ScriptRun(
        console,
        budget=budget,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=field_policy(),
    )


def _pos_dump(console: WorldConsole) -> dict:
    return console.pos().model_dump()


# ---- face_direction ----


def face_direction(console: WorldConsole, direction: str) -> ScriptResult:
    """转向：已面向则 no-op；否则按一次方向键，`moved` 如实报（前方可走会真移动）。"""
    if direction not in DIRECTIONS:
        return _reject(direction)
    run = _run(console, budget=1)
    before = console.pos()
    if console.facing() == direction:
        return run.finish(
            ok=True,
            code="ok",
            extra={"moved": False, "facing": direction, "final_pos": _pos_dump(console)},
        )
    res = run.execute([BUTTON_OF[direction]])
    res.data.update(
        {
            "moved": console.pos() != before,
            "facing": console.facing() or direction,
            "final_pos": _pos_dump(console),
        }
    )
    return res


# ---- walk_to_adjacent ----


def walk_to_adjacent(console: WorldConsole, direction: str) -> ScriptResult:
    """相邻一步：到位 = 成功；没动 = `blocked`（一步即判）。落点是草丛则 `entered_grass`。"""
    if direction not in DIRECTIONS:
        return _reject(direction)
    run = _run(console, budget=1)
    before = console.pos()
    dx, dy = STEP_OF[direction]
    res = run.execute([BUTTON_OF[direction]])
    moved = console.pos() != before
    res.data.update(
        {
            "final_pos": _pos_dump(console),
            "entered_grass": console.is_grass(before.x + dx, before.y + dy) if moved else False,
        }
    )
    if res.code == "ok" and not moved:
        res.ok, res.code = False, "blocked"
    return res


# ---- walk_to ----


def walk_to(console: WorldConsole, x: int, y: int, max_steps: int = 200) -> ScriptResult:
    """按 RAM 地形自动寻路到本图目标；逐键更新视野并重规划。

    BFS 可先远离目标绕障，视野外目标通过可达边界探索。墙/NPC/招牌不可作
    落点；门只允许作为目标，台阶只按箭头跳跃。不可达返回 blocked；每次实际
    按键（含被挡或触发中断）消耗一步，达到 max_steps 返回 budget_exhausted。
    战斗、选项和换图沿原 field_policy 中断并保留事件。
    """
    run = _run(console, budget=max_steps)
    terrain = WalkingMap()
    target = (x, y)
    steps = 0
    try:
        while True:
            here = console.pos()
            point = (here.x, here.y)
            if point == target:
                return run.finish(
                    ok=True, code="ok", extra={"final_pos": _pos_dump(console), "steps_used": steps}
                )
            if run.budget <= 0:
                break
            terrain.observe(console.terrain())
            button = terrain.next_button(point, target)
            if button is None:
                return run.finish(
                    ok=False,
                    code="blocked",
                    extra={"final_pos": _pos_dump(console), "steps_used": steps},
                )
            run.budget -= 1
            steps += 1
            if not run.press(button):
                terrain.blocked.add((point, button))
    except Halt as halt:
        data = {"final_pos": _pos_dump(console), "steps_used": steps}
        data.update(halt.extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=data)
    return run.finish(
        ok=False,
        code="budget_exhausted",
        extra={"final_pos": _pos_dump(console), "steps_used": steps},
    )


# ---- circle_walk ----


def circle_walk(console: WorldConsole, laps: int, extent: int = 1) -> ScriptResult:
    """绕圈：每轮四段（east×d / south×d / west×d / north×d），每步断言位移、
    圈末断言回起点；位移 0 → `off_course`。预算 = 所需步数 + 容差。"""
    if laps < 1 or extent < 1:
        return ScriptResult(ok=False, code="rejected", data={"laps": laps, "extent": extent})
    run = _run(console, budget=laps * extent * 4 + 4)
    start = console.pos()
    lap_dirs = ["east"] * extent + ["south"] * extent + ["west"] * extent + ["north"] * extent
    seq = lap_dirs * laps
    per_lap = extent * 4
    laps_done = 0
    try:
        for i, d in enumerate(seq):
            if run.budget <= 0:
                return run.finish(
                    ok=False,
                    code="budget_exhausted",
                    extra={"laps_done": laps_done, "final_pos": _pos_dump(console)},
                )
            run.budget -= 1
            if not run.press(BUTTON_OF[d]):
                return run.finish(
                    ok=False,
                    code="off_course",
                    extra={"laps_done": laps_done, "final_pos": _pos_dump(console)},
                )
            if (i + 1) % per_lap == 0:
                if console.pos() != start:
                    return run.finish(
                        ok=False,
                        code="off_course",
                        extra={"laps_done": laps_done, "final_pos": _pos_dump(console)},
                    )
                laps_done += 1
    except Halt as halt:
        data = {"laps_done": laps_done, "final_pos": _pos_dump(console)}
        data.update(halt.extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=data)
    return run.finish(
        ok=True, code="ok", extra={"laps_done": laps_done, "final_pos": _pos_dump(console)}
    )


# ---- bounce_in_tall_grass ----


def bounce_in_tall_grass(console: WorldConsole, steps: int = 30) -> ScriptResult:
    """草丛里双方向来回走撞怪：进战斗 = 目的达成（`ok:true, battle_started`，
    §6.2 bounce 捕获 BattleStarted 为正常终止）；步数用完无怪 → `no_encounter`（合法）；
    起点不是草丛 → `rejected`。来回顶到草丛边缘不判 blocked（不查位移）。"""
    here = console.pos()
    if not console.is_grass(here.x, here.y):
        return ScriptResult(ok=False, code="rejected", data={"pos": here.model_dump()})
    run = _run(console, budget=steps)
    used = 0
    try:
        while used < steps:
            run.budget -= 1
            used += 1
            run.press(BUTTON_OF["north" if used % 2 else "south"])  # 双方向来回
    except Halt as halt:
        if halt.code == "battle_started":
            return run.finish(
                ok=True, code="battle_started", extra={"steps_used": used, "encounter": True}
            )
        data: dict[str, Any] = {"steps_used": used, "encounter": False}
        data.update(halt.extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=data)
    return run.finish(ok=True, code="no_encounter", extra={"steps_used": used, "encounter": False})


__all__ = [
    "BUTTON_OF",
    "DIRECTIONS",
    "STEP_OF",
    "bounce_in_tall_grass",
    "circle_walk",
    "face_direction",
    "walk_to",
    "walk_to_adjacent",
]
