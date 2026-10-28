"""导航 / 场所类脚本（§7.5）：exit_map / heal_at_center。

两者都依赖 `tables/` 静态表（`engine.WARPS` / `engine.POKECENTER_LAYOUTS`）——
表是白名单机制，不在表里的 map → `unsupported_map`；表里坐标过期导致的
换图失败 → `warp_failed`（修表，不是脚本兜底）。

**机械确认 YES**：`heal_at_center` 走到护士的"是否回血"YES/NO 选项时，按
脚本目的（回血）机械选 YES——与 `shop_buy` 代答确认是同性质的"固定流程确认"，
不是模型分叉，故在 `choice_presented` 钩子上直接确认并继续，不冻结。
"""

from __future__ import annotations

from typing import Any

from ..readout import read_party
from .engine import (
    POKECENTER_LAYOUTS,
    WARPS,
    Halt,
    ScriptResult,
    ScriptRun,
    WorldConsole,
)
from .movement import BUTTON_OF, _run, face_direction, walk_to
from .policies import ScriptPolicy, StableWait


class _StillTalking(Exception):
    """对话预算耗尽的内部信号（不污染脚本结局码命名空间）。"""


# ---- exit_map ----


def exit_map(console: WorldConsole, target_warp: int = -1) -> ScriptResult:
    """离开当前地图：查 `tables/warps[map_id]` 的出口（门 warp 带坐标、边缘出口只有方向）。

    - 门 warp：先 `walk_to` 到门口，途中被挡 → `blocked` / `not_converging`；
    - 朝触发方向反复走：踩到出口换图（`MapChanged` 钩子）→ `ok`；
    - 路径被挡 → `blocked`；持续可移动但预算耗尽仍不换图 → `warp_failed`；
    - map 不在白名单 → `unsupported_map`；`target_warp` 越界 → `rejected`。
    """
    layout = WARPS.get(str(console.map_id()))
    if layout is None:
        return ScriptResult(ok=False, code="unsupported_map", data={"map_id": console.map_id()})
    doors = list(layout.get("door_warps", []) or [])
    edges = list(layout.get("edge_exits", []) or [])
    exits = doors + edges  # 门优先
    if not exits:
        return ScriptResult(ok=False, code="unsupported_map", data={"map_id": console.map_id()})
    idx = target_warp if target_warp >= 0 else 0
    if not (0 <= idx < len(exits)):
        return ScriptResult(ok=False, code="rejected", data={"target_warp": target_warp})
    exit = exits[idx]

    # 门 warp：先走到门口
    if "x" in exit and "y" in exit:
        res = walk_to(console, int(exit["x"]), int(exit["y"]))
        if res.code == "map_changed":
            res.ok, res.code = True, "ok"
            res.data["to_map"] = console.map_id()
            return res
        if not res.ok:
            return res  # blocked / not_converging / budget_exhausted 原样透传

    direction = exit.get("dir")
    # 表里的 dir 两种口径都收：语义方向（north → BUTTON_OF 换算）或直接按键名（up）
    button = BUTTON_OF.get(direction, direction)
    if button not in set(BUTTON_OF.values()):
        return ScriptResult(ok=False, code="rejected", data={"dir": direction})
    run = _run(console, budget=80)
    try:
        while run.budget > 0:
            run.budget -= 1
            if not run.press(button):
                return run.finish(
                    ok=False,
                    code="blocked",
                    extra={"dir": direction},
                )
            # MapChanged 钩子会抛 Halt
        return run.finish(
            ok=False, code="warp_failed", extra={"dir": direction, "map_id": console.map_id()}
        )
    except Halt as halt:
        if halt.code == "map_changed":
            return run.finish(
                ok=True, code="ok", extra={"dir": direction, "to_map": halt.extra.get("map_id")}
            )
        # 中途进战斗 / 出选项：如实上报
        return run.finish(ok=halt.ok, code=halt.code, extra=halt.extra)


# ---- heal_at_center ----


def heal_at_center(console: WorldConsole, max_steps: int = 60) -> ScriptResult:
    """在宝可梦中心回满血：查表定位护士与站位 → `walk_to` 到站位 → 面朝护士 →
    按 a 触发对话 → 遇"是否回血"YES/NO 选项机械确认 YES → 推进对话到回野外 →
    读队伍 RAM 校验全满。

    - map 非白名单 → `unsupported_map`；
    - 去站位途中被挡 / 预算耗尽 → 透传 `walk_to` 的码；
    - 对话推不完 → `still_talking`；
    - 队伍 HP 未全满 → `verify_failed`。
    """
    layout = POKECENTER_LAYOUTS.get(str(console.map_id()))
    if layout is None:
        return ScriptResult(ok=False, code="unsupported_map", data={"map_id": console.map_id()})
    stand = layout["stand"]

    # ① 走到站位（面朝护士）
    res = walk_to(console, int(stand["x"]), int(stand["y"]), max_steps=max_steps)
    if not res.ok:
        return res

    # ② 面朝护士（护士格应不可走，否则会位移；face_direction 已面向则 no-op）
    face_direction(console, stand["facing"])

    # ③ 触发并推进对话（钩子在 YES/NO 选项处抛 choice_presented，就地确认 YES）
    run = _run(console, budget=max_steps)
    try:
        run.press("a")  # 开场白
        _advance_to_walk(run, console)
    except _StillTalking:
        return run.finish(ok=False, code="still_talking", extra=_heal_extra(run, console))
    except Halt as halt:
        if halt.code == "choice_presented" and console.read().options in (
            ["YES", "NO"],
            ["HEAL", "CANCEL"],
        ):
            _confirm_heal(console)
            try:
                _advance_to_walk(run, console)
            except _StillTalking:
                return run.finish(ok=False, code="still_talking", extra=_heal_extra(run, console))
            except Halt as halt2:
                return run.finish(ok=halt2.ok, code=halt2.code, extra=halt2.extra)
        else:
            return run.finish(ok=halt.ok, code=halt.code, extra=halt.extra)

    # ④ 校验队伍 HP 全满
    party = read_party(console.memory)
    if not party or any(m.hp < m.max_hp for m in party):
        return run.finish(
            ok=False,
            code="verify_failed",
            extra={
                "party": [{"species": m.species, "hp": m.hp, "max_hp": m.max_hp} for m in party]
            },
        )
    return run.finish(ok=True, code="ok", extra={"healed": True, "party_size": len(party)})


def _advance_to_walk(run: ScriptRun, console: WorldConsole) -> None:
    """对话推进循环：反复按 a 直到回野外；预算耗尽抛 `_StillTalking`；
    中途的 choice / battle 由 `ScriptRun.press` 抛 `Halt` 透传给调用方。"""
    while True:
        if run.budget <= 0:
            raise _StillTalking
        run.budget -= 1
        run.press("a")
        if console.scene() == "walk":
            return


def _confirm_heal(console: WorldConsole) -> None:
    """在 YES/NO 或 HEAL/CANCEL 上确认回血：先把光标移到第一项，再按 a。

    本步骤经 ScriptRun，等待动画且不启用选项中断；目标第一项来自已核对的回血选项。
    """
    run = ScriptRun(
        console,
        budget=0,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=ScriptPolicy(wait=StableWait(minimum_frames=64)),
    )
    text = console.read()
    if text.cursor and text.cursor != text.options[0]:
        run.press("up")
    run.press("a")


def _heal_extra(run: ScriptRun, console: WorldConsole) -> dict[str, Any]:
    return {
        "final_screen_text": console.read().screen,
    }


__all__ = ["exit_map", "heal_at_center"]
