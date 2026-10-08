"""学新招要忘旧招（`learn_move`）的脚本：`forget` / `skip`，外加这个场合的视图。

初态："Delete an older move to make room for …?" 的 YES / NO（`scene.at_start`）。
忘招：YES → "Which move should be forgotten?" 招式列表选一招；
不学：NO → "Abandon learning …?" 答 YES。
之后推完话，停在下一个 `▶`（背包列表、战斗选单……）。
学招的是队伍里第 `wWhichPokemon` 0xCF92 只，想学的招是 `wMoveNum` 0xD0E0。
"""

from __future__ import annotations

from ...interface import (
    ActionEntry,
    LearnMoveView,
    Memory,
    ScreenText,
    ScriptParam,
    TaskScene,
)
from ...moves import fold, move_name
from ..definitions import ScriptDefinition
from ..engine import Abort, ScriptRun
from ..execution_types import ScriptReason
from .common import answer, answer_yes, cursor_index, party
from .policy import menu_policy

W_WHICH_POKEMON = 0xCF92
W_MOVE_NUM = 0xD0E0


def learn_view(mem: Memory) -> LearnMoveView:
    """这一帧的学招视图。"""
    mon = party(mem)[mem[W_WHICH_POKEMON]]
    return LearnMoveView(pokemon=mon.name, new_move=move_name(mem[W_MOVE_NUM]), moves=mon.moves)


def _moves(run: ScriptRun, index: int) -> list[str]:
    return [m.name for m in party(run.mem)[index].moves]


def _stop(run: ScriptRun, text: ScreenText) -> str:
    if text.has_cursor and run.scene_now() is not TaskScene.LEARN_MOVE:
        return f"停在 {run.scene_now().value}：▶{text.cursor}" if text.cursor else "停在选单"
    if not text.screen:
        return "画面上没有字了"
    return ""


def _check_forget(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    known = _moves(run, run.mem[W_WHICH_POKEMON])
    if fold(str(args["move"])) not in [fold(m) for m in known]:
        return (
            ScriptReason.UNKNOWN_MOVE,
            f"现有的招里没有 {args['move']}（有：{'、'.join(known)}）",
        )
    return None


def _execute_forget(run: ScriptRun, args: dict[str, str | int]) -> str:
    new = move_name(run.mem[W_MOVE_NUM])
    old = fold(str(args["move"]))
    index = run.mem[W_WHICH_POKEMON]
    # 步骤 1：答 YES，等招式列表。
    answer(run, "YES")
    run.wait_for(lambda t: "forgotten" in t.dialog_text and t.has_cursor, expect="招式列表出现")
    # 步骤 2：光标挪到要忘的招，按 A。
    target = [fold(o) for o in run.screen().options].index(old)
    run.move_to(lambda: cursor_index(run.screen()), target, what="招式光标")
    run.press_screen("a", expect=f"忘掉 {args['move']}")
    # 步骤 3：推完话，核学会了。
    stop = run.advance(lambda t: _stop(run, t))
    known = _moves(run, index)
    if new not in known:
        raise Abort(ScriptReason.CANNOT_USE, f"没有学会 {new}（现在：{'、'.join(known)}）；{stop}")
    return f"忘掉 {args['move']}，学会 {new}；现在：{'、'.join(known)}；{stop}"


def _check_skip(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    return None


def _execute_skip(run: ScriptRun, args: dict[str, str | int]) -> str:
    new = move_name(run.mem[W_MOVE_NUM])
    # 步骤 1：答 NO，再在 "Abandon learning …?" 上答 YES。
    answer(run, "NO")
    answer_yes(run, "「Abandon learning」YES / NO 出现")
    # 步骤 2：推完话。
    stop = run.advance(lambda t: _stop(run, t))
    return f"不学 {new}；{stop}"


LEARN_SCRIPTS: dict[str, ScriptDefinition] = {
    "forget": ScriptDefinition(
        spec=ActionEntry(
            kind="script",
            name="forget",
            params=[ScriptParam(name="move", type="str", description="要忘掉的招，照视图里的写")],
            description="忘掉一招、学新招（秘传招式忘不掉）",
        ),
        scene=TaskScene.LEARN_MOVE,
        check=_check_forget,
        execute=_execute_forget,
        policy=menu_policy(rewind_after=False),
    ),
    "skip": ScriptDefinition(
        spec=ActionEntry(kind="script", name="skip", description="不学这招"),
        scene=TaskScene.LEARN_MOVE,
        check=_check_skip,
        execute=_execute_skip,
        policy=menu_policy(rewind_after=False),
    ),
}

__all__ = ["LEARN_SCRIPTS", "learn_view"]
