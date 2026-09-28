"""商店买卖（`shop_items`）的宏：`buy` / `sell` / `quit`，外加这个场合的视图。

初态：`▶BUY / SELL / QUIT` 主菜单画着（`scene.at_start`）。
地址与流程见 `docs/perceive/p0-findings.md`（常青市商店实测）：商品表 `wItemList` 0xCF7B，
列表光标 `wCurrentMenuItem` 0xCC26 + `wListScrollOffset` 0xCC36，
数量 `wItemQuantity` 0xCF96（`up` 加一）。
"""

from __future__ import annotations

from ..interface import (
    BagEntry,
    MacroParam,
    MacroReason,
    MacroSpec,
    Memory,
    ScreenText,
    ShopItem,
    ShopItemsView,
    TaskScene,
)
from ..items import item_id, item_name, item_price
from ..readout import read_bag, read_money
from .engine import Abort, MacroDef, MacroRun

W_ITEM_LIST = 0xCF7B
"""`wItemList`：第一个字节是件数，其后是道具 id，`0xFF` 收尾。"""
W_CURRENT_MENU_ITEM = 0xCC26
W_LIST_SCROLL_OFFSET = 0xCC36
W_ITEM_QUANTITY = 0xCF96
LIST_END = 0xFF
MAX_QUANTITY = 99
BAG_SLOTS = 20
MENU = ("BUY", "SELL", "QUIT")


def shop_view(mem: Memory, rom: bytes) -> ShopItemsView:
    """这一帧的商店视图：商品（名、单价）、金钱、背包。"""
    return ShopItemsView(
        items=[ShopItem(name=item_name(i), price=item_price(rom, i) or 0) for i in _goods(mem)],
        money=read_money(mem),
        bag=[BagEntry(name=item_name(b.item_id), quantity=b.quantity) for b in read_bag(mem)],
    )


def _goods(mem: Memory) -> list[int]:
    goods: list[int] = []
    for i in range(1, mem[W_ITEM_LIST] + 1):
        item = mem[W_ITEM_LIST + i]
        if item == LIST_END:
            break
        goods.append(item)
    return goods


def _bag_counts(mem: Memory) -> dict[int, int]:
    return {b.item_id: b.quantity for b in read_bag(mem)}


def _quantity(run: MacroRun, args: dict[str, str | int]) -> int:
    return int(args["quantity"])


# ---- buy ----


def _check_buy(run: MacroRun, args: dict[str, str | int]) -> tuple[MacroReason, str] | None:
    mem, name, n = run.mem, str(args["item"]), _quantity(run, args)
    item = item_id(name)
    if item is None or item not in _goods(mem):
        return MacroReason.UNKNOWN_ITEM, f"店里没有 {name}"
    if not 1 <= n <= MAX_QUANTITY:
        return MacroReason.QUANTITY_OUT_OF_RANGE, f"数量要在 1–{MAX_QUANTITY}，给的是 {n}"
    price = item_price(run.console.rom, item) or 0
    if price * n > read_money(mem):
        return MacroReason.NOT_ENOUGH_MONEY, f"要 ¥{price * n}，只有 ¥{read_money(mem)}"
    bag = _bag_counts(mem)
    if item in bag and bag[item] + n > MAX_QUANTITY:
        return (
            MacroReason.BAG_FULL,
            f"背包里 {name} 已有 {bag[item]}，再买 {n} 会超过 {MAX_QUANTITY}",
        )
    if item not in bag and len(bag) >= BAG_SLOTS:
        return MacroReason.BAG_FULL, f"背包 {BAG_SLOTS} 格已满"
    return None


def _execute_buy(run: MacroRun, args: dict[str, str | int]) -> str:
    mem, n = run.mem, _quantity(run, args)
    item = item_id(str(args["item"]))
    assert item is not None
    price = item_price(run.console.rom, item) or 0
    money0, have0 = read_money(mem), _bag_counts(mem).get(item, 0)

    # 步骤 1：主菜单选 BUY，等商品列表。
    _open(run, "BUY")
    # 步骤 2：光标挪到这件商品，打开数量框。
    _pick(run, _goods(mem).index(item), item_name(item))
    # 步骤 3：调数量，确认价钱，选 YES。
    _confirm_quantity(run, n)
    # 步骤 4：核钱与背包。
    money1, have1 = read_money(mem), _bag_counts(mem).get(item, 0)
    if money1 != money0 - price * n or have1 != have0 + n:
        raise Abort(
            MacroReason.UNEXPECTED_SCREEN,
            f"买完钱 {money0}→{money1}、{item_name(item)} {have0}→{have1}，与预期不符",
        )
    return f"钱 {money0}→{money1}，{item_name(item)} +{n}"


# ---- sell ----


def _check_sell(run: MacroRun, args: dict[str, str | int]) -> tuple[MacroReason, str] | None:
    mem, name, n = run.mem, str(args["item"]), _quantity(run, args)
    item = item_id(name)
    bag = _bag_counts(mem)
    if item is None or item not in bag:
        return MacroReason.NOT_IN_BAG, f"背包里没有 {name}"
    if not 1 <= n <= bag[item]:
        return MacroReason.QUANTITY_OUT_OF_RANGE, f"{name} 只有 {bag[item]} 个，给的是 {n}"
    if item_price(run.console.rom, item) == 0:
        return MacroReason.KEY_ITEM, f"{name} 不能卖"
    return None


def _execute_sell(run: MacroRun, args: dict[str, str | int]) -> str:
    mem, n = run.mem, _quantity(run, args)
    item = item_id(str(args["item"]))
    assert item is not None
    money0, have0 = read_money(mem), _bag_counts(mem)[item]
    index = [b.item_id for b in read_bag(mem)].index(item)

    # 步骤 1：主菜单选 SELL，等背包列表。
    _open(run, "SELL")
    # 步骤 2：光标挪到这件道具，打开数量框。
    _pick(run, index, item_name(item))
    # 步骤 3：调数量，确认价钱，选 YES。
    _confirm_quantity(run, n)
    # 步骤 4：核钱与背包。
    money1, have1 = read_money(mem), _bag_counts(mem).get(item, 0)
    if money1 <= money0 or have1 != have0 - n:
        raise Abort(
            MacroReason.UNEXPECTED_SCREEN,
            f"卖完钱 {money0}→{money1}、{item_name(item)} {have0}→{have1}，与预期不符",
        )
    return f"钱 {money0}→{money1}，{item_name(item)} −{n}"


# ---- quit ----


def _check_quit(run: MacroRun, args: dict[str, str | int]) -> tuple[MacroReason, str] | None:
    return None


def _execute_quit(run: MacroRun, args: dict[str, str | int]) -> str:
    # 步骤 1：主菜单选 QUIT。
    run.move_to(lambda: run.mem[W_CURRENT_MENU_ITEM], MENU.index("QUIT"), what="主菜单光标")
    run.press("a", expect="离开买卖菜单")
    # 步骤 2：道别的话推完，直到离开本场合。
    run.wait_for(lambda _t: run.scene_now() is not TaskScene.SHOP_ITEMS, expect="离开买卖菜单")
    return "离开买卖菜单"


# ---- 共用步骤 ----


def _open(run: MacroRun, option: str) -> None:
    """主菜单选 `option`（BUY / SELL），等它的列表出现。"""
    run.move_to(lambda: run.mem[W_CURRENT_MENU_ITEM], MENU.index(option), what="主菜单光标")
    run.press("a", expect=f"打开 {option} 列表")
    run.wait_for(_list_open, expect=f"{option} 列表出现")


def _pick(run: MacroRun, index: int, name: str) -> None:
    """列表光标挪到第 `index` 项（核光标文字是 `name`），按 A 打开数量框。"""
    run.move_to(
        lambda: run.mem[W_CURRENT_MENU_ITEM] + run.mem[W_LIST_SCROLL_OFFSET], index, what="列表光标"
    )
    cursor = run.screen().cursor
    if item_id(cursor) != item_id(name):
        raise Abort(MacroReason.UNEXPECTED_SCREEN, f"光标在 {cursor!r}，不是 {name}")
    run.press("a", expect="数量框出现", ok=lambda t: t.quantity_box)
    run.wait_for(lambda t: t.quantity_box, expect="数量框出现")


def _confirm_quantity(run: MacroRun, n: int) -> None:
    """数量调到 `n`，按 A，推完价钱的话，在 YES/NO 上选 YES。"""
    run.move_to(lambda: run.mem[W_ITEM_QUANTITY], n, what="数量", increase="up")
    run.press("a", expect="报价")
    text = run.wait_for(
        lambda t: t.options == ["YES", "NO"],
        expect="YES / NO 出现",
        advance=lambda t: not t.has_cursor,
    )
    if text.cursor != "YES":
        run.press("up", expect="光标到 YES", ok=lambda t: t.cursor == "YES")
    run.press("a", expect="成交")
    run.settle()


def _list_open(text: ScreenText) -> bool:
    """列表开着：实心光标在列表里（不在主菜单、不在 YES/NO）、没有数量框。"""
    return (
        text.has_cursor
        and not text.quantity_box
        and text.cursor not in MENU
        and text.options != ["YES", "NO"]
    )


_ITEM = MacroParam(name="item", type="str", description="道具名，照视图里的写")
_QTY = MacroParam(name="quantity", type="int", description="数量，1–99")

SHOP_MACROS: dict[str, MacroDef] = {
    "buy": MacroDef(
        spec=MacroSpec(
            name="buy",
            params=[_ITEM, _QTY],
            description="买：道具必须是视图「商品」里的；钱要够、背包要有空位",
        ),
        scene=TaskScene.SHOP_ITEMS,
        check=_check_buy,
        execute=_execute_buy,
    ),
    "sell": MacroDef(
        spec=MacroSpec(
            name="sell",
            params=[_ITEM, _QTY],
            description="卖：道具必须在视图「背包」里，数量不超过持有数；重要道具不能卖",
        ),
        scene=TaskScene.SHOP_ITEMS,
        check=_check_sell,
        execute=_execute_sell,
    ),
    "quit": MacroDef(
        spec=MacroSpec(name="quit", description="结束买卖，离开这个菜单"),
        scene=TaskScene.SHOP_ITEMS,
        check=_check_quit,
        execute=_execute_quit,
        rewind_after=False,
    ),
}


__all__ = ["SHOP_MACROS", "shop_view"]
