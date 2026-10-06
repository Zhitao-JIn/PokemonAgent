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

CONVERGE_WINDOW = 5
"""walk_to 每 N 步校验一次距离收敛（§7.2）。"""

REVERSE: dict[str, str] = {"east": "west", "west": "east", "south": "north", "north": "south"}
"""反方向表：walk_to 上一步成功位移的反方向在下一步降权（防绕墙摆动）。"""


def _reject(direction: str) -> ScriptResult:
    return ScriptResult(ok=False, code="rejected", data={"direction": direction})


def _run(console: WorldConsole, budget: int) -> ScriptRun:
    return ScriptRun(
        console, budget=budget, start_map_id=console.map_id(), start_pos=console.pos()
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
    """走到目标格：固定轴序取缩短曼哈顿距离的方向，被挡换另一轴试一次，
    仍不动 `blocked`；每 5 步校验距离收敛，不收敛 `not_converging`。不做 BFS
    （绕行决策交调用方——§7.2）。"""
    run = _run(console, budget=max_steps)
    start = console.pos()
    target = (x, y)
    dist = lambda p: abs(p.x - x) + abs(p.y - y)  # noqa: E731 —— 单点闭包
    steps = 0
    last_dist = dist(start)
    last_dir: str | None = None
    try:
        while steps < max_steps:
            here = console.pos()
            if (here.x, here.y) == target:
                return run.finish(
                    ok=True, code="ok", extra={"final_pos": _pos_dump(console), "steps_used": steps}
                )
            # 候选：所有严格缩短距离的方向，固定轴序（先 x 后 y）；
            # 上一步刚走过来的反方向降到最后（防绕墙时来回摆），除非它是唯一候选。
            cands = []
            if x != here.x:
                cands.append("east" if x > here.x else "west")
            if y != here.y:
                cands.append("south" if y > here.y else "north")
            if last_dir is not None and len(cands) > 1:
                cands.sort(key=lambda d: d == REVERSE[last_dir])
            moved = False
            for d in cands:
                if run.press(BUTTON_OF[d]):
                    moved, last_dir = True, d
                    break
            if not moved:
                # 换另一轴试一次（§7.2）：cands 只含一个轴时换另一轴（该轴与目标
                # 同位，方向不定 → 固定序两侧试：x 先 east 后 west，y 先 south 后 north）。
                if y != here.y:
                    alts = ["east", "west"]
                elif x != here.x:
                    alts = ["south", "north"]
                else:
                    alts = []
                for d in alts:
                    if run.press(BUTTON_OF[d]):
                        moved, last_dir = True, d
                        break
            steps += 1
            if not moved:
                return run.finish(
                    ok=False,
                    code="blocked",
                    extra={"final_pos": _pos_dump(console), "steps_used": steps},
                )
            if steps % CONVERGE_WINDOW == 0:
                now = dist(console.pos())
                if now >= last_dist:
                    return run.finish(
                        ok=False,
                        code="not_converging",
                        extra={"final_pos": _pos_dump(console), "steps_used": steps},
                    )
                last_dist = now
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
    return run.finish(
        ok=True, code="no_encounter", extra={"steps_used": used, "encounter": False}
    )


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
