"""野外背包（`bag`）的脚本：`use` / `toss` / `close`，外加这个场合的视图。

初态：背包列表画着、实心 `▶` 在列表里（`scene.at_start`）。
选中道具后弹 `USE / TOSS` 子菜单；用药要在队伍列表里选对象，丢要调数量、再答 YES。
"""

from __future__ import annotations

from ...interface import (
    ActionEntry,
    BagView,
    Memory,
    ScreenText,
    ScriptParam,
    TaskScene,
)
from ...items import item_id, item_name, item_price
from ..definitions import ScriptDefinition
from ..engine import Abort, ScriptRun
from ..execution_types import ScriptReason
from .common import (
    HEAL_ITEMS,
    answer_yes,
    bag,
    bag_count,
    bag_index,
    choose,
    find_mon,
    party,
    pick_mon,
    pick_row,
    set_quantity,
    unknown_mon,
    useless,
)
from .policy import menu_policy

REPELS = frozenset({0x1E, 0x38, 0x39})
"""REPEL / SUPER REPEL / MAX REPEL：直接用，不选对象。"""
GROWTH_ITEMS = frozenset({0x0A, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2F})
"""进化石五种、HP UP 等营养剂五种、RARE CANDY：要选对象，有没有效果由游戏判。"""
TARGET_ITEMS = HEAL_ITEMS | GROWTH_ITEMS


def bag_view(mem: Memory) -> BagView:
    """这一帧的背包视图：背包、队伍。"""
    return BagView(bag=bag(mem), party=party(mem))


def _in_list(text: ScreenText) -> bool:
    """回到背包列表：实心光标在列表里，不在子菜单、YES/NO、数量框上。"""
    return (
        text.has_cursor
        and not text.quantity_box
        and text.options not in (["USE", "TOSS"], ["YES", "NO"])
        and "Use item on which" not in text.dialog_text
    )


# ---- use ----


def _check_use(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    mem, name, who = run.mem, str(args["item"]), str(args["pokemon"])
    item = item_id(name)
    if item is None or bag_count(mem, item) == 0:
        return ScriptReason.NOT_IN_BAG, f"背包里没有 {name}"
    if item in REPELS:
        return None
    if item not in TARGET_ITEMS:
        return ScriptReason.CANNOT_USE, f"{item_name(item)} 的用法脚本里还没有"
    if not who:
        return ScriptReason.TARGET_REQUIRED, f"{item_name(item)} 要指定用在哪只身上（pokemon）"
    mons = party(mem)
    index = find_mon(mons, who)
    if index is None:
        return unknown_mon(mons, who)
    return useless(item, mons[index]) if item in HEAL_ITEMS else None


def _execute_use(run: ScriptRun, args: dict[str, str | int]) -> str:
    mem = run.mem
    item = item_id(str(args["item"]))
    assert item is not None
    have0 = bag_count(mem, item)
    head = f"用 {item_name(item)}"
    # 步骤 1：列表选这件道具，子菜单选 USE。
    pick_row(run, bag_index(mem, item), item_name(item))
    run.wait_for(lambda t: t.options == ["USE", "TOSS"], expect="USE / TOSS 子菜单出现")
    choose(run, "USE")
    # 步骤 2：要选对象的，在队伍列表里选它。
    if item in TARGET_ITEMS:
        run.wait_for(lambda t: "Use item on which" in t.dialog_text, expect="选对象的队伍列表出现")
        mons = party(mem)
        who = find_mon(mons, str(args["pokemon"]))
        assert who is not None
        hp0 = mons[who].hp
        pick_mon(run, who, mons[who].name)
        head += f"（对 {mons[who].name}）"
    # 步骤 3：推完话，直到回到背包列表或离开背包（学新招、进化）。
    stop = run.advance(lambda t: _stop(run, t))
    have1 = bag_count(mem, item)
    if have1 == have0 and run.scene_now() is TaskScene.BAG:
        raise Abort(ScriptReason.CANNOT_USE, f"{item_name(item)} 没有用掉；{stop}")
    if item in HEAL_ITEMS:
        after = party(mem)[who]
        head += f"：HP {hp0}→{after.hp}，状态 {after.status}"
    return f"{head}；{stop}"


def _stop(run: ScriptRun, text: ScreenText) -> str:
    """停在下一个 `▶`：回到背包列表，或别的选单（学新招的 YES / NO 等）。

    只认光标——换画面时会有几百帧整屏空白，按场合判会误以为已经离开。
    """
    if not text.has_cursor:
        return ""
    scene = run.scene_now()
    if scene is TaskScene.BAG and _in_list(text):
        return "回到背包列表"
    return f"停在 {scene.value}：▶{text.cursor}" if text.cursor else f"停在 {scene.value}"


# ---- toss ----


def _check_toss(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    mem, name, n = run.mem, str(args["item"]), int(args["quantity"])
    item = item_id(name)
    have = bag_count(mem, item) if item is not None else 0
    if item is None or have == 0:
        return ScriptReason.NOT_IN_BAG, f"背包里没有 {name}"
    if not 1 <= n <= have:
        return ScriptReason.QUANTITY_OUT_OF_RANGE, f"{item_name(item)} 只有 {have} 个，给的是 {n}"
    if item_price(run.console.rom, item) == 0:
        return ScriptReason.KEY_ITEM, f"{item_name(item)} 是重要道具，不能丢"
    return None


def _execute_toss(run: ScriptRun, args: dict[str, str | int]) -> str:
    mem, n = run.mem, int(args["quantity"])
    item = item_id(str(args["item"]))
    assert item is not None
    have0 = bag_count(mem, item)
    # 步骤 1：列表选这件道具，子菜单选 TOSS。
    pick_row(run, bag_index(mem, item), item_name(item))
    run.wait_for(lambda t: t.options == ["USE", "TOSS"], expect="USE / TOSS 子菜单出现")
    choose(run, "TOSS")
    # 步骤 2：调数量，答 YES。
    set_quantity(run, n)
    answer_yes(run, "「Is it OK to toss」YES / NO 出现")
    # 步骤 3：推完话回到列表，核数量。
    run.wait_for(_in_list, expect="回到背包列表", advance=lambda t: not t.has_cursor)
    have1 = bag_count(mem, item)
    if have1 != have0 - n:
        raise Abort(
            ScriptReason.UNEXPECTED_SCREEN, f"丢完 {item_name(item)} {have0}→{have1}，与预期不符"
        )
    return f"丢掉 {item_name(item)} ×{n}（{have0}→{have1}）"


# ---- close ----


def _check_close(run: ScriptRun, args: dict[str, str | int]) -> tuple[ScriptReason, str] | None:
    return None


def _execute_close(run: ScriptRun, args: dict[str, str | int]) -> str:
    run.press_screen("b", expect="关上背包")
    run.wait_for(lambda _t: run.scene_now() is not TaskScene.BAG, expect="离开背包")
    return f"关上背包，到了 {run.scene_now().value}"


_ITEM = ScriptParam(name="item", type="str", description="道具名，照视图「背包」里的写")
_WHO = ScriptParam(
    name="pokemon",
    type="str",
    default="",
    description="用在哪只身上（药、进化石、营养剂、RARE CANDY 要给；驱虫喷雾不给）",
)
_QTY = ScriptParam(name="quantity", type="int", description="数量，不超过持有数")

BAG_SCRIPTS: dict[str, ScriptDefinition] = {
    "use": ScriptDefinition(
        policy=menu_policy(),
        spec=ActionEntry(
            kind="script",
            name="use",
            params=[_ITEM, _WHO],
            description="用道具：药、进化石、营养剂、RARE CANDY 对一只队员用；驱虫喷雾直接用",
        ),
        scene=TaskScene.BAG,
        check=_check_use,
        execute=_execute_use,
    ),
    "toss": ScriptDefinition(
        policy=menu_policy(),
        spec=ActionEntry(
            kind="script", name="toss", params=[_ITEM, _QTY], description="丢道具；重要道具不能丢"
        ),
        scene=TaskScene.BAG,
        check=_check_toss,
        execute=_execute_toss,
    ),
    "close": ScriptDefinition(
        spec=ActionEntry(kind="script", name="close", description="关上背包"),
        scene=TaskScene.BAG,
        check=_check_close,
        execute=_execute_close,
        policy=menu_policy(rewind_after=False),
    ),
}

__all__ = ["BAG_SCRIPTS", "bag_view"]
