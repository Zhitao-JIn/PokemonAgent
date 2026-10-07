"""战斗选单（`battle_menu`）与统一换人（`battle_switch`）的接管脚本及视图。

初态：行动菜单 `▶FIGHT PKMN / ITEM RUN` 画着（`battle_menu`）；队伍列表画着（`battle_switch`）。
出招、换人、用道具、逃跑之后自动推进战斗文字，遇到任意 `▶`、战斗标志清零或推进上限即停，
停下的画面交还给 JEV（下一个选单、单层 YES/NO、战斗结束后的野外）。
地址按 `pret/pokered` 链接符号表：出场宝可梦招式 `wBattleMonMoves` 0xD01C /
PP `wBattleMonPP` 0xD02D，队伍 `wPartyMon1` 0xD16B 起每只 44 字节，
昵称 `wPartyMonNicks` 0xD2B5 起每个 11 字节，在场的是第几只 `wPlayerMonNumber` 0xCC2F。
"""

from __future__ import annotations

from ...battle_status import read_battle_status
from ...interface import (
    ActionEntry,
    BattleMenuView,
    BattleSwitchView,
    Memory,
    MonEntry,
    ScreenText,
    ScriptParam,
    TaskScene,
)
from ...items import item_id, item_name
from ...moves import fold
from ...screen_text import W_IS_IN_BATTLE
from ..definitions import ScriptDefinition
from ..engine import Abort, ScriptRun
from ..execution_types import ScriptReason
from .common import (
    BALLS,
    HEAL_ITEMS,
    bag,
    bag_count,
    bag_index,
    check_target,
    cursor_index,
    find_mon,
    moves,
    party,
    pick_mon,
    pick_row,
    unknown_mon,
    useless,
)
from .policy import menu_policy

W_BATTLE_MON_MOVES = 0xD01C
W_BATTLE_MON_PP = 0xD02D
W_PLAYER_MON_NUMBER = 0xCC2F
TRAINER_BATTLE = 2
"""`wIsInBattle`：1 野战，2 训练家对战。"""

SELF_ITEMS = frozenset({0x2E, 0x37, 0x3A, 0x41, 0x42, 0x43, 0x44})
"""X ACCURACY / GUARD SPEC. / DIRE HIT / X 系列四种：用在在场的那只，不选对象。"""
TARGET_ITEMS = HEAL_ITEMS


# ---- 读内存 ----


def _party(mem: Memory) -> list[MonEntry]:
    """队伍，在场的那只标出来。"""
    return party(mem, active=mem[W_PLAYER_MON_NUMBER] if mem[W_IS_IN_BATTLE] else -1)


def battle_view(mem: Memory) -> BattleMenuView | None:
    """这一帧的战斗选单视图；不在战斗时为 None。"""
    status = read_battle_status(mem)
    if status is None:
        return None
    mine, foe = status.mine, status.foe
    return BattleMenuView(
        mine=MonEntry(
            name=mine.name,
            level=mine.level,
            hp=mine.hp,
            max_hp=mine.max_hp,
            status=mine.status,
            active=True,
            moves=moves(mem, W_BATTLE_MON_MOVES, W_BATTLE_MON_PP),
        ),
        foe=MonEntry(
            name=foe.name, level=foe.level, hp=foe.hp, max_hp=foe.max_hp, status=foe.status
        ),
        trainer=mem[W_IS_IN_BATTLE] == TRAINER_BATTLE,
        party=_party(mem),
        bag=bag(mem),
    )


def switch_view(mem: Memory) -> BattleSwitchView:
    """战斗换人的统一视图：队伍。"""
    return BattleSwitchView(party=_party(mem))


# ---- 共用步骤 ----


def _action(run: ScriptRun, option: str) -> None:
    """行动菜单上把光标挪到 `option`（二维格子，按行列走），按 A。"""
    for _ in range(8):
        text = run.screen()
        target = _cell(text, option)
        if target is None:
            raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"行动菜单里没有 {option}")
        now = text.cursor_cell
        if now == target:
            run.press_screen("a", expect=f"选 {option}")
            return
        if now is None:
            raise Abort(ScriptReason.UNEXPECTED_SCREEN, "行动菜单上没有光标")
        key = (
            ("down" if target[0] > now[0] else "up")
            if target[0] != now[0]
            else ("right" if target[1] > now[1] else "left")
        )
        run.press_screen(key, expect=f"光标 → {option}")
    raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"光标挪不到 {option}")


def _cell(text: ScreenText, option: str) -> tuple[int, int] | None:
    for r, row in enumerate(text.option_grid):
        for c, name in enumerate(row):
            if name == option:
                return r, c
    return None


def _advance(run: ScriptRun) -> str:
    """推进战斗文字，遇到 `▶`、战斗标志清零即停（`ScriptRun.advance`），返回停在哪。

    停在战斗选单的子层（推进时误按进了招式列表等）就按 B 退回行动菜单。
    """
    stop = run.advance(lambda t: _stop(run, t))
    if run.scene is TaskScene.BATTLE_MENU and run.scene_now() is TaskScene.BATTLE_MENU:
        run.rewind()
        stop = _stop(run, run.screen()) or stop
    return stop


def _stop(run: ScriptRun, text: ScreenText) -> str:
    if run.mem[W_IS_IN_BATTLE] == 0:
        return "战斗结束"
    if text.options == ["YES", "NO"]:
        return f"停在 YES/NO：{text.dialog_text}"
    if text.has_cursor:
        return f"停在选单：▶{text.cursor}" if text.cursor else "停在选单"
    return ""


def _hp_line(run: ScriptRun, before: tuple[int, int, str, str]) -> str:
    """出招前后的 HP 变化（双方）。"""
    status = read_battle_status(run.mem)
    mine0, foe0, name0, foe_name0 = before
    if status is None:
        return ""
    parts = []
    if status.foe.name == foe_name0:
        parts.append(f"对手 {foe_name0} HP {foe0}→{status.foe.hp}")
    else:
        parts.append(f"对手换成 {status.foe.name}")
    if status.mine.name == name0:
        parts.append(f"我方 {name0} HP {mine0}→{status.mine.hp}")
    else:
        parts.append(f"我方换成 {status.mine.name} HP {status.mine.hp}")
    return "，".join(parts)


def _snapshot(run: ScriptRun) -> tuple[int, int, str, str]:
    status = read_battle_status(run.mem)
    assert status is not None, "战斗接管脚本在战斗外被调"
    return status.mine.hp, status.foe.hp, status.mine.name, status.foe.name


def _summary(head: str, run: ScriptRun, before: tuple[int, int, str, str], stop: str) -> str:
    hp = _hp_line(run, before)
    return "；".join(p for p in (head, hp, stop) if p)


# ---- fight ----


def _check_fight(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    known = moves(run.mem, W_BATTLE_MON_MOVES, W_BATTLE_MON_PP)
    hit = next((m for m in known if fold(m.name) == fold(str(args["move"]))), None)
    if hit is None:
        names = "、".join(m.name for m in known)
        return ScriptReason.UNKNOWN_MOVE, f"在场的宝可梦不会 {args['move']}（会：{names}）"
    if hit.pp == 0:
        return ScriptReason.NO_PP, f"{hit.name} 没有 PP 了"
    return None


def _execute_fight(run: ScriptRun, args: dict[str, str | int]) -> str:
    before = _snapshot(run)
    move = fold(str(args["move"]))
    # 步骤 1：行动菜单选 FIGHT，等招式列表。
    _action(run, "FIGHT")
    text = run.wait_for(
        lambda t: t.has_cursor and move in [fold(o) for o in t.options], expect="招式列表出现"
    )
    # 步骤 2：光标挪到这招，按 A。
    target = [fold(o) for o in text.options].index(move)
    run.move_to(lambda: cursor_index(run.screen()), target, what="招式光标")
    run.press_screen("a", expect=f"出招 {args['move']}")
    # 步骤 3：推进战斗文字。
    stop = _advance(run)
    return _summary(f"用 {text.options[target]}", run, before, stop)


# ---- switch ----


def _check_switch(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    return check_target(_party(run.mem), str(args["pokemon"]), need_bench=True)


def _execute_switch(run: ScriptRun, args: dict[str, str | int]) -> str:
    before = _snapshot(run)
    index = find_mon(_party(run.mem), str(args["pokemon"]))
    assert index is not None
    name = _party(run.mem)[index].name
    # 步骤 1：行动菜单选 PKMN，等队伍列表。
    _action(run, "PKMN")
    run.wait_for(lambda t: "Choose a POK" in t.dialog_text, expect="队伍列表出现")
    # 步骤 2：选这只，子菜单选 SWITCH。
    pick_mon(run, index, name)
    run.wait_for(lambda t: t.cursor == "SWITCH", expect="SWITCH / STATS 子菜单出现")
    run.press_screen("a", expect=f"换上 {name}")
    # 步骤 3：推进战斗文字，核在场的是它。
    stop = _advance(run)
    if run.mem[W_IS_IN_BATTLE] and run.mem[W_PLAYER_MON_NUMBER] != index:
        raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"推进完在场的不是 {name}")
    return _summary(f"换上 {name}", run, before, stop)


# ---- use_item ----


def _check_use(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    mem, name, who = run.mem, str(args["item"]), str(args["pokemon"])
    item = item_id(name)
    if item is None or bag_count(mem, item) == 0:
        return ScriptReason.NOT_IN_BAG, f"背包里没有 {name}"
    if item in BALLS:
        if mem[W_IS_IN_BATTLE] == TRAINER_BATTLE:
            return ScriptReason.CANNOT_USE, "训练家对战不能扔球"
        return None
    if item in SELF_ITEMS:
        return None
    if item not in TARGET_ITEMS:
        return ScriptReason.CANNOT_USE, f"{item_name(item)} 不能在战斗里用"
    if not who:
        return ScriptReason.TARGET_REQUIRED, f"{item_name(item)} 要指定用在哪只身上（pokemon）"
    mons = _party(mem)
    index = find_mon(mons, who)
    if index is None:
        return unknown_mon(mons, who)
    return useless(item, mons[index])


def _execute_use(run: ScriptRun, args: dict[str, str | int]) -> str:
    mem = run.mem
    before = _snapshot(run)
    item = item_id(str(args["item"]))
    assert item is not None
    have0 = bag_count(mem, item)
    # 步骤 1：行动菜单选 ITEM，等背包列表。
    _action(run, "ITEM")
    run.wait_for(lambda t: t.has_cursor and "CANCEL" in t.options, expect="背包列表出现")
    # 步骤 2：光标挪到这件道具，按 A。
    pick_row(run, bag_index(mem, item), item_name(item))
    # 步骤 3：要选对象的，在队伍列表里选它。
    head = f"用 {item_name(item)}"
    if item in TARGET_ITEMS:
        run.wait_for(lambda t: "Use item on which" in t.dialog_text, expect="选对象的队伍列表出现")
        who = find_mon(_party(mem), str(args["pokemon"]))
        assert who is not None
        pick_mon(run, who, str(args["pokemon"]))
        head += f"（对 {_party(mem)[who].name}）"
    # 步骤 4：推进战斗文字；球看抓没抓到（球要等抓捕流程走完才从背包扣），其余核道具少了一个。
    stop = _advance(run)
    if item in BALLS:
        caught = any("caught" in step.actual for step in run.steps)
        return _summary(f"{head}：{'抓到了' if caught else '没抓到'}", run, before, stop)
    have1 = bag_count(mem, item)
    if have1 != have0 - 1:
        raise Abort(ScriptReason.CANNOT_USE, f"{item_name(item)} 没有用掉；{stop}")
    return _summary(head, run, before, stop)


# ---- run ----


def _check_run(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    if run.mem[W_IS_IN_BATTLE] == TRAINER_BATTLE:
        return ScriptReason.CANNOT_USE, "训练家对战不能逃"
    return None


def _execute_run(run: ScriptRun, args: dict[str, str | int]) -> str:
    before = _snapshot(run)
    # 步骤 1：行动菜单选 RUN。
    _action(run, "RUN")
    # 步骤 2：推进文字。
    stop = _advance(run)
    head = "逃走了" if run.mem[W_IS_IN_BATTLE] == 0 else "没逃掉"
    return _summary(head, run, before, stop) if head == "没逃掉" else f"{head}；{stop}"


# ---- send_out ----


def _check_send(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    return check_target(_party(run.mem), str(args["pokemon"]), need_bench=True)


def _execute_send(run: ScriptRun, args: dict[str, str | int]) -> str:
    index = find_mon(_party(run.mem), str(args["pokemon"]))
    assert index is not None
    name = _party(run.mem)[index].name
    # 步骤 1：队伍列表选这只。
    pick_mon(run, index, name)
    # 步骤 2：有子菜单就选 SWITCH，然后推进文字。
    text = run.screen()
    if text.cursor == "SWITCH":
        run.press_screen("a", expect=f"换上 {name}")
    stop = _advance(run)
    if run.mem[W_IS_IN_BATTLE] and run.mem[W_PLAYER_MON_NUMBER] != index:
        raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"推进完在场的不是 {name}")
    return f"换上 {name}；{stop}"


_MOVE = ScriptParam(name="move", type="str", description="招式名，照视图「招式」里的写")
_MON = ScriptParam(name="pokemon", type="str", description="宝可梦昵称，照视图「队伍」里的写")
_ITEM = ScriptParam(name="item", type="str", description="道具名，照视图「背包」里的写")
_WHO = ScriptParam(
    name="pokemon",
    type="str",
    default="",
    description="用在哪只身上（伤药、解异常、复活要给；球与 X 系列不给）",
)

BATTLE_TAKEOVERS: dict[str, ScriptDefinition] = {
    "fight": ScriptDefinition(
        spec=ActionEntry(
            kind="script",
            name="fight",
            params=[_MOVE],
            description="出招：招式必须是在场宝可梦的且还有 PP；之后自动推进到下一个选单或战斗结束",
        ),
        scene=TaskScene.BATTLE_MENU,
        check=_check_fight,
        execute=_execute_fight,
        policy=menu_policy(rewind_after=False),
    ),
    "switch": ScriptDefinition(
        spec=ActionEntry(
            kind="script",
            name="switch",
            params=[_MON],
            description="换人：换上一只没倒下、不在场的队员；对手会趁机出招",
        ),
        scene=TaskScene.BATTLE_MENU,
        check=_check_switch,
        execute=_execute_switch,
        policy=menu_policy(rewind_after=False),
    ),
    "use_item": ScriptDefinition(
        spec=ActionEntry(
            kind="script",
            name="use_item",
            params=[_ITEM, _WHO],
            description="用道具：扔球、给队员喝药 / 解异常 / 复活、X 系列；用掉一回合",
        ),
        scene=TaskScene.BATTLE_MENU,
        check=_check_use,
        execute=_execute_use,
        policy=menu_policy(rewind_after=False),
    ),
    "run": ScriptDefinition(
        spec=ActionEntry(
            kind="script", name="run", description="逃跑（只限野生宝可梦；不一定逃得掉）"
        ),
        scene=TaskScene.BATTLE_MENU,
        check=_check_run,
        execute=_execute_run,
        policy=menu_policy(rewind_after=False),
    ),
}

SWITCH_TAKEOVERS: dict[str, ScriptDefinition] = {
    "send_out": ScriptDefinition(
        spec=ActionEntry(
            kind="script",
            name="send_out",
            params=[_MON],
            description="换人：选择未倒下且不在场的队员；之后自动推进到下一个选单",
        ),
        scene=TaskScene.BATTLE_SWITCH,
        check=_check_send,
        execute=_execute_send,
        policy=menu_policy(rewind_after=False),
    ),
}

__all__ = ["BATTLE_TAKEOVERS", "SWITCH_TAKEOVERS", "battle_view", "switch_view"]
