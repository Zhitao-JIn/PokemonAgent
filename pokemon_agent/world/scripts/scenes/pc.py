"""PC（`pc`）的脚本：道具存取与丢弃、宝可梦存取、换箱、关机，外加这个场合的视图。

初态：选哪台 PC 的主菜单
（`BILL's PC` 或 `SOMEONE's PC` / `<主角>'s PC` / `PROF.OAK's PC` / `LOG OFF`）。
道具走主角的 PC（第二项），宝可梦与换箱走比尔的 PC（第一项）。打开时的
"Accessed …" 那几句话显示时，主菜单的光标还画着，要替它推。
地址按 `pret/pokered` 链接符号表：PC 道具 `wNumBoxItems` 0xD53A；当前箱 `wBoxCount` 0xDA80、
`wBoxMons` 0xDA96 起每只 33 字节（等级 +3）、昵称 `wBoxMonNicks` 0xDE06；
箱号 `wCurrentBoxNum` 0xD5A0。
"""

from __future__ import annotations

from ...interface import (
    ActionEntry,
    BagEntry,
    BoxEntry,
    Memory,
    PcView,
    ScreenText,
    ScriptParam,
    TaskScene,
)
from ...items import item_id, item_name, item_price
from ...moves import fold
from ...ram import NAME_LENGTH
from ..definitions import Check, Execute, ScriptDefinition
from ..engine import Abort, ScriptRun
from ..execution_types import ScriptReason
from .common import (
    MAX_QUANTITY,
    answer_yes,
    bag,
    bag_count,
    bag_index,
    choose,
    find_mon,
    nick,
    party,
    pick_mon,
    pick_row,
    set_quantity,
    unknown_mon,
)
from .policy import menu_policy

W_NUM_BOX_ITEMS = 0xD53A
PC_ITEM_CAPACITY = 50
BAG_CAPACITY = 20
W_BOX_COUNT = 0xDA80
W_BOX_MONS = 0xDA96
BOX_MON_SIZE = 33
BOX_MON_LEVEL = 3
W_BOX_MON_NICKS = 0xDE06
BOX_CAPACITY = 20
W_CURRENT_BOX_NUM = 0xD5A0
BOX_NUM_MASK = 0x7F
PARTY_CAPACITY = 6
ITEM_MENU = ("WITHDRAW ITEM", "DEPOSIT ITEM", "TOSS ITEM")
BILL_MENU = ("WITHDRAW PKMN", "DEPOSIT PKMN", "RELEASE PKMN", "CHANGE BOX")


def pc_view(mem: Memory) -> PcView:
    """这一帧的 PC 视图。"""
    return PcView(
        items=[BagEntry(name=item_name(i), quantity=q) for i, q in _pc_items(mem)],
        bag=bag(mem),
        box=_box(mem),
        box_number=(mem[W_CURRENT_BOX_NUM] & BOX_NUM_MASK) + 1,
        party=party(mem),
    )


def _pc_items(mem: Memory) -> list[tuple[int, int]]:
    items: list[tuple[int, int]] = []
    for i in range(min(mem[W_NUM_BOX_ITEMS], PC_ITEM_CAPACITY)):
        item = mem[W_NUM_BOX_ITEMS + 1 + 2 * i]
        if item == 0xFF:
            break
        items.append((item, mem[W_NUM_BOX_ITEMS + 2 + 2 * i]))
    return items


def _pc_count(mem: Memory, item: int) -> int:
    return sum(q for i, q in _pc_items(mem) if i == item)


def _box(mem: Memory) -> list[BoxEntry]:
    return [
        BoxEntry(
            name=nick(mem, W_BOX_MON_NICKS + i * NAME_LENGTH),
            level=mem[W_BOX_MONS + i * BOX_MON_SIZE + BOX_MON_LEVEL],
        )
        for i in range(min(mem[W_BOX_COUNT], BOX_CAPACITY))
    ]


# ---- 共用步骤 ----


def _open(run: ScriptRun, which: int, menu: tuple[str, ...]) -> None:
    """主菜单选第 `which` 台 PC，推完 "Accessed …"，等它的菜单出现。"""
    choose(run, run.screen().options[which])
    run.wait_for(
        lambda t: menu[0] in t.options,
        expect=f"{menu[0]} 菜单出现",
        advance=lambda t: bool(t.dialog_text) and menu[0] not in t.options,
    )


def _back_to(menu_option: str):  # noqa: ANN202
    return lambda t: menu_option in t.options and t.has_cursor


def _list_open(text: ScreenText) -> bool:
    return text.has_cursor and "CANCEL" in text.options and not text.quantity_box


# ---- 道具 ----


def _check_items(
    run: ScriptRun, args: dict[str, str | int], source: str
) -> tuple[ScriptReason, str] | None:
    mem, name, n = run.mem, str(args["item"]), int(args["quantity"])
    item = item_id(name)
    have = (
        0 if item is None else (bag_count(mem, item) if source == "bag" else _pc_count(mem, item))
    )
    where = "背包" if source == "bag" else "PC"
    if item is None or have == 0:
        return ScriptReason.NOT_IN_BAG, f"{where}里没有 {name}"
    if not 1 <= n <= have:
        return (
            ScriptReason.QUANTITY_OUT_OF_RANGE,
            f"{where}里 {item_name(item)} 只有 {have} 个，给的是 {n}",
        )
    return None


def _check_withdraw_item(
    run: ScriptRun, args: dict[str, str | int]
) -> tuple[ScriptReason, str] | None:
    rejected = _check_items(run, args, "pc")
    if rejected:
        return rejected
    item = item_id(str(args["item"]))
    assert item is not None
    have = bag_count(run.mem, item)
    if have + int(args["quantity"]) > MAX_QUANTITY:
        return ScriptReason.BAG_FULL, f"背包里 {item_name(item)} 会超过 {MAX_QUANTITY}"
    if have == 0 and len(bag(run.mem)) >= BAG_CAPACITY:
        return ScriptReason.BAG_FULL, f"背包 {BAG_CAPACITY} 格已满"
    return None


def _check_deposit_item(
    run: ScriptRun, args: dict[str, str | int]
) -> tuple[ScriptReason, str] | None:
    rejected = _check_items(run, args, "bag")
    if rejected:
        return rejected
    item = item_id(str(args["item"]))
    assert item is not None
    if _pc_count(run.mem, item) == 0 and len(_pc_items(run.mem)) >= PC_ITEM_CAPACITY:
        return ScriptReason.BAG_FULL, f"PC 道具 {PC_ITEM_CAPACITY} 格已满"
    return None


def _check_toss_item(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    rejected = _check_items(run, args, "pc")
    if rejected:
        return rejected
    item = item_id(str(args["item"]))
    if item is not None and item_price(run.console.rom, item) == 0:
        return ScriptReason.KEY_ITEM, f"{item_name(item)} 是重要道具，不能丢"
    return None


def _move_items(run: ScriptRun, args: dict[str, str | int], action: str) -> str:
    """道具三件事的共同流程：主角的 PC → 选动作 → 列表选道具 → 数量 →（丢要答 YES）→ 回列表。"""
    mem, n = run.mem, int(args["quantity"])
    item = item_id(str(args["item"]))
    assert item is not None
    bag0, pc0 = bag_count(mem, item), _pc_count(mem, item)
    index = (
        bag_index(mem, item)
        if action == "DEPOSIT ITEM"
        else [i for i, _ in _pc_items(mem)].index(item)
    )
    key = item_price(run.console.rom, item) == 0
    # 步骤 1：打开主角的 PC，选动作，等列表。
    _open(run, 1, ITEM_MENU)
    choose(run, action)
    run.wait_for(_list_open, expect="道具列表出现")
    # 步骤 2：选道具；重要道具没有数量框。
    pick_row(run, index, item_name(item))
    if not key:
        set_quantity(run, n)
    if action == "TOSS ITEM":
        answer_yes(run, "「Is it OK to toss」YES / NO 出现")
    # 步骤 3：推完话回到列表，核两边数量。
    run.wait_for(_list_open, expect="回到道具列表", advance=lambda t: not t.has_cursor)
    bag1, pc1 = bag_count(mem, item), _pc_count(mem, item)
    moved = {"WITHDRAW ITEM": (n, -n), "DEPOSIT ITEM": (-n, n), "TOSS ITEM": (0, -n)}[action]
    if (bag1 - bag0, pc1 - pc0) != moved:
        raise Abort(
            ScriptReason.UNEXPECTED_SCREEN,
            f"{item_name(item)} 背包 {bag0}→{bag1}、PC {pc0}→{pc1}，与预期不符",
        )
    return f"{item_name(item)} ×{n}：背包 {bag0}→{bag1}，PC {pc0}→{pc1}"


# ---- 宝可梦 ----


def _check_withdraw_mon(
    run: ScriptRun, args: dict[str, str | int]
) -> tuple[ScriptReason, str] | None:
    name = str(args["pokemon"])
    box = _box(run.mem)
    if not any(fold(m.name) == fold(name) for m in box):
        names = "、".join(m.name for m in box) or "（空）"
        return ScriptReason.UNKNOWN_POKEMON, f"当前箱里没有 {name}（有：{names}）"
    if len(party(run.mem)) >= PARTY_CAPACITY:
        return ScriptReason.BAG_FULL, "队伍已经 6 只"
    return None


def _check_deposit_mon(
    run: ScriptRun, args: dict[str, str | int]
) -> tuple[ScriptReason, str] | None:
    mons = party(run.mem)
    if find_mon(mons, str(args["pokemon"])) is None:
        return unknown_mon(mons, str(args["pokemon"]))
    if len(mons) < 2:
        return ScriptReason.CANNOT_USE, "队伍只剩一只，不能存"
    if len(_box(run.mem)) >= BOX_CAPACITY:
        return ScriptReason.BAG_FULL, "当前箱已满"
    return None


def _move_mon(run: ScriptRun, args: dict[str, str | int], action: str) -> str:
    """宝可梦存取：比尔的 PC → 选动作 → 列表选这只 → 子菜单 → 回菜单。"""
    mem = run.mem
    name = str(args["pokemon"])
    withdraw = action == "WITHDRAW PKMN"
    if withdraw:
        index = [fold(m.name) for m in _box(mem)].index(fold(name))
    else:
        found = find_mon(party(mem), name)
        assert found is not None
        index = found
    party0, box0 = len(party(mem)), len(_box(mem))
    # 步骤 1：打开比尔的 PC，选动作，等列表。
    _open(run, 0, BILL_MENU)
    choose(run, action)
    run.wait_for(_list_open, expect="宝可梦列表出现")
    # 步骤 2：选这只，子菜单选 WITHDRAW / DEPOSIT。
    pick_mon(run, index, name)
    verb = "WITHDRAW" if withdraw else "DEPOSIT"
    run.wait_for(lambda t: t.cursor in (verb, "STATS", "CANCEL"), expect=f"{verb} 子菜单出现")
    choose(run, verb)
    # 步骤 3：推完话回到比尔的菜单，核两边只数。
    run.wait_for(_back_to(action), expect="回到比尔的 PC 菜单")
    party1, box1 = len(party(mem)), len(_box(mem))
    step = 1 if withdraw else -1
    if (party1 - party0, box1 - box0) != (step, -step):
        raise Abort(
            ScriptReason.UNEXPECTED_SCREEN,
            f"队伍 {party0}→{party1}、箱 {box0}→{box1}，与预期不符",
        )
    return f"{'取出' if withdraw else '存入'} {name}：队伍 {party0}→{party1}，箱 {box0}→{box1}"


# ---- 换箱 ----


def _check_change_box(
    run: ScriptRun, args: dict[str, str | int]
) -> tuple[ScriptReason, str] | None:
    n = int(args["n"])
    if not 1 <= n <= 12:
        return ScriptReason.QUANTITY_OUT_OF_RANGE, f"箱号要在 1–12，给的是 {n}"
    return None


def _execute_change_box(run: ScriptRun, args: dict[str, str | int]) -> str:
    n = int(args["n"])
    before = (run.mem[W_CURRENT_BOX_NUM] & BOX_NUM_MASK) + 1
    label = f"BOX{n:2d}"
    # 步骤 1：比尔的 PC 选 CHANGE BOX，推完存档提示，答 YES。
    _open(run, 0, BILL_MENU)
    choose(run, "CHANGE BOX")
    answer_yes(run, "「Is that okay?」YES / NO 出现")
    # 步骤 2：选箱，等存完回到菜单。
    run.wait_for(lambda t: label in t.options, expect="箱子列表出现")
    choose(run, label)
    run.idle_until(_back_to("CHANGE BOX"), expect="存完回到比尔的 PC 菜单")
    after = (run.mem[W_CURRENT_BOX_NUM] & BOX_NUM_MASK) + 1
    if after != n:
        raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"当前箱是 {after}，不是 {n}")
    return f"当前箱 BOX {before} → BOX {after}（换箱时游戏存了档）"


# ---- 关机 ----


def _check_none(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    return None


def _execute_log_off(run: ScriptRun, args: dict[str, str | int]) -> str:
    choose(run, "LOG OFF")
    run.wait_for(lambda _t: run.scene_now() is not TaskScene.PC, expect="离开 PC")
    return "关上 PC"


_ITEM = ScriptParam(name="item", type="str", description="道具名，照视图里的写")
_QTY = ScriptParam(name="quantity", type="int", description="数量")
_MON = ScriptParam(name="pokemon", type="str", description="宝可梦昵称，照视图里的写")


def _def(
    name: str,
    params: list[ScriptParam],
    description: str,
    check: Check,
    execute: Execute,
    rewind: bool = True,
) -> ScriptDefinition:
    return ScriptDefinition(
        policy=menu_policy(rewind_after=rewind),
        spec=ActionEntry(kind="script", name=name, params=params, description=description),
        scene=TaskScene.PC,
        check=check,
        execute=execute,
    )


PC_SCRIPTS: dict[str, ScriptDefinition] = {
    "withdraw_item": _def(
        "withdraw_item",
        [_ITEM, _QTY],
        "从 PC 取道具到背包",
        _check_withdraw_item,
        lambda r, a: _move_items(r, a, "WITHDRAW ITEM"),
    ),
    "deposit_item": _def(
        "deposit_item",
        [_ITEM, _QTY],
        "把背包里的道具存进 PC",
        _check_deposit_item,
        lambda r, a: _move_items(r, a, "DEPOSIT ITEM"),
    ),
    "toss_item": _def(
        "toss_item",
        [_ITEM, _QTY],
        "丢掉 PC 里的道具；重要道具不能丢",
        _check_toss_item,
        lambda r, a: _move_items(r, a, "TOSS ITEM"),
    ),
    "withdraw_pokemon": _def(
        "withdraw_pokemon",
        [_MON],
        "从当前箱取一只到队伍（队伍满 6 只不能取）",
        _check_withdraw_mon,
        lambda r, a: _move_mon(r, a, "WITHDRAW PKMN"),
    ),
    "deposit_pokemon": _def(
        "deposit_pokemon",
        [_MON],
        "把队伍里的一只存进当前箱（队伍只剩一只不能存）",
        _check_deposit_mon,
        lambda r, a: _move_mon(r, a, "DEPOSIT PKMN"),
    ),
    "change_box": _def(
        "change_box",
        [ScriptParam(name="n", type="int", description="箱号 1–12")],
        "换当前箱（游戏会存一次档）",
        _check_change_box,
        _execute_change_box,
    ),
    "log_off": _def("log_off", [], "关上 PC", _check_none, _execute_log_off, rewind=False),
}

__all__ = ["PC_SCRIPTS", "pc_view"]
