"""野外队伍列表（`party`）的接管脚本：`switch` / `field_move` / `stats` / `close`，
外加这个场合的视图。

初态：队伍列表画着、实心 `▶` 在某一只上（`scene.at_start`）。选中一只弹子菜单：
会的野外招式在前，其后 `STATS / SWITCH / CANCEL`。换位置选 SWITCH 后再选另一只。
"""

from __future__ import annotations

from ...interface import (
    ActionEntry,
    Memory,
    PartyView,
    ScreenText,
    ScriptParam,
    TaskScene,
)
from ...moves import fold
from .common import choose, find_mon, party, pick_mon, unknown_mon
from .engine import Abort, TakeoverDef, TakeoverRun
from .outcome import TakeoverReason

FIELD_MOVES = ("CUT", "FLY", "SURF", "STRENGTH", "FLASH", "DIG", "TELEPORT", "SOFTBOILED")
"""能在队伍子菜单里直接用的招。"""
UNSUPPORTED_FIELD_MOVES = ("FLY",)
"""用了还要再选目的地的招，接管脚本里还没有。"""


def party_view(mem: Memory) -> PartyView:
    """这一帧的队伍视图。"""
    return PartyView(party=party(mem))


def _submenu(run: TakeoverRun, index: int, name: str) -> None:
    """选中第 `index` 只，等子菜单出现。"""
    pick_mon(run, index, name)
    run.wait_for(lambda t: "CANCEL" in t.options and "STATS" in t.options, expect="子菜单出现")


def _home(text: ScreenText) -> bool:
    """回到队伍列表的底部提示。"""
    return "Choose a POK" in text.dialog_text


# ---- switch ----


def _check_switch(
    run: TakeoverRun, args: dict[str, str | int]
) -> tuple[TakeoverReason, str] | None:
    mons = party(run.mem)
    a, b = find_mon(mons, str(args["a"])), find_mon(mons, str(args["b"]))
    if a is None:
        return unknown_mon(mons, str(args["a"]))
    if b is None:
        return unknown_mon(mons, str(args["b"]))
    if a == b:
        return TakeoverReason.BAD_ARGS, "两只是同一只"
    return None


def _execute_switch(run: TakeoverRun, args: dict[str, str | int]) -> str:
    mons = party(run.mem)
    a, b = find_mon(mons, str(args["a"])), find_mon(mons, str(args["b"]))
    assert a is not None and b is not None
    names0 = [m.name for m in mons]
    # 步骤 1：选第一只，子菜单选 SWITCH。
    _submenu(run, a, names0[a])
    choose(run, "SWITCH")
    run.wait_for(lambda t: "Move POK" in t.dialog_text, expect="「Move POKéMON where?」")
    # 步骤 2：选第二只。
    pick_mon(run, b, names0[b])
    run.wait_for(_home, expect="回到队伍列表")
    # 步骤 3：核顺序对调。
    names1 = [m.name for m in party(run.mem)]
    if names1[a] != names0[b] or names1[b] != names0[a]:
        raise Abort(TakeoverReason.UNEXPECTED_SCREEN, f"换完顺序是 {names1}，与预期不符")
    return f"{names0[a]} 与 {names0[b]} 换了位置：{'、'.join(names1)}"


# ---- field_move ----


def _check_field(run: TakeoverRun, args: dict[str, str | int]) -> tuple[TakeoverReason, str] | None:
    mons = party(run.mem)
    index = find_mon(mons, str(args["pokemon"]))
    move = fold(str(args["move"]))
    if index is None:
        return unknown_mon(mons, str(args["pokemon"]))
    if move not in FIELD_MOVES:
        return TakeoverReason.CANNOT_USE, f"{args['move']} 不是能在野外用的招"
    if move in UNSUPPORTED_FIELD_MOVES:
        return TakeoverReason.CANNOT_USE, f"{move} 用了还要选目的地，接管脚本里还没有"
    if move not in [fold(m.name) for m in mons[index].moves]:
        return TakeoverReason.UNKNOWN_MOVE, f"{mons[index].name} 不会 {move}"
    return None


def _execute_field(run: TakeoverRun, args: dict[str, str | int]) -> str:
    mons = party(run.mem)
    index = find_mon(mons, str(args["pokemon"]))
    assert index is not None
    move = fold(str(args["move"]))
    # 步骤 1：选这只，子菜单选这招。
    _submenu(run, index, mons[index].name)
    choose(run, move)
    # 步骤 2：推完话；回到队伍列表说明没用成。
    stop = run.advance(lambda t: _field_stop(run, t))
    if run.scene_now() is TaskScene.PARTY:
        said = next(
            (x.actual for x in reversed(run.steps) if x.actual and "Choose a POK" not in x.actual),
            stop,
        )
        raise Abort(TakeoverReason.CANNOT_USE, f"{move} 没用成：{said}")
    return f"{mons[index].name} 用了 {move}；{stop}"


def _field_stop(run: TakeoverRun, text: ScreenText) -> str:
    scene = run.scene_now()
    if scene is not TaskScene.PARTY:
        return f"离开队伍列表，到了 {scene.value}"
    if _home(text) and text.has_cursor:
        return "回到队伍列表"
    return ""


# ---- stats ----


def _check_stats(run: TakeoverRun, args: dict[str, str | int]) -> tuple[TakeoverReason, str] | None:
    mons = party(run.mem)
    return (
        unknown_mon(mons, str(args["pokemon"]))
        if find_mon(mons, str(args["pokemon"])) is None
        else None
    )


def _execute_stats(run: TakeoverRun, args: dict[str, str | int]) -> str:
    mons = party(run.mem)
    index = find_mon(mons, str(args["pokemon"]))
    assert index is not None
    _submenu(run, index, mons[index].name)
    choose(run, "STATS")
    run.wait_for(
        lambda _t: run.scene_now() is TaskScene.POKEMON_INFO,
        expect="能力页出现",
        advance=lambda _t: False,
    )
    return f"打开 {mons[index].name} 的能力页"


# ---- close ----


def _check_close(run: TakeoverRun, args: dict[str, str | int]) -> tuple[TakeoverReason, str] | None:
    return None


def _execute_close(run: TakeoverRun, args: dict[str, str | int]) -> str:
    run.press("b", expect="关上队伍列表")
    run.wait_for(lambda _t: run.scene_now() is not TaskScene.PARTY, expect="离开队伍列表")
    return f"关上队伍列表，到了 {run.scene_now().value}"


_MON = ScriptParam(name="pokemon", type="str", description="宝可梦昵称，照视图「队伍」里的写")

PARTY_TAKEOVERS: dict[str, TakeoverDef] = {
    "switch": TakeoverDef(
        spec=ActionEntry(
            kind="script",
            name="switch",
            params=[
                ScriptParam(name="a", type="str", description="一只的昵称"),
                ScriptParam(name="b", type="str", description="另一只的昵称"),
            ],
            description="对调两只在队伍里的位置（排第一的先出场）",
        ),
        scene=TaskScene.PARTY,
        check=_check_switch,
        execute=_execute_switch,
    ),
    "field_move": TakeoverDef(
        spec=ActionEntry(
            kind="script",
            name="field_move",
            params=[_MON, ScriptParam(name="move", type="str", description="招式名")],
            description="用野外招式（CUT / SURF / STRENGTH / FLASH / DIG / TELEPORT / "
            "SOFTBOILED）；FLY 还不支持",
        ),
        scene=TaskScene.PARTY,
        check=_check_field,
        execute=_execute_field,
        rewind_after=False,
    ),
    "stats": TakeoverDef(
        spec=ActionEntry(
            kind="script",
            name="stats",
            params=[_MON],
            description="打开一只的能力页（之后照常按键翻页、退出）",
        ),
        scene=TaskScene.PARTY,
        check=_check_stats,
        execute=_execute_stats,
        rewind_after=False,
    ),
    "close": TakeoverDef(
        spec=ActionEntry(kind="script", name="close", description="关上队伍列表"),
        scene=TaskScene.PARTY,
        check=_check_close,
        execute=_execute_close,
        rewind_after=False,
    ),
}

__all__ = ["PARTY_TAKEOVERS", "party_view"]
