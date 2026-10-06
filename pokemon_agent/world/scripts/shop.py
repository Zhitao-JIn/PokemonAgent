"""商店类脚本（§7.1）：buy_item / sell_item。

**价格真源**：买价与在售清单来自 `shop_layouts.goods`，卖价来自 ROM 道具价格；**机械校验**：终态对账
（money 差额、stock 增量）→ 对不上 `verify_failed` 兜底；**接管脚本代答**：确认框
由接管脚本 `shop_buy` / `shop_sell` 机械代答（非分叉），本脚本只看它的 `ok` 与结局码。
卖价按 Gen1 规则 = 买价一半（`price // 2`）。
"""

from __future__ import annotations

from typing import Any

from ..items import item_id, item_price
from .engine import SHOP_LAYOUTS, Abort, ScriptResult, ScriptRun, WorldConsole
from .interruptions import field_policy
from .movement import face_direction, walk_to
from .policies import ScriptPolicy, StableWait


def _enter_shop(console: WorldConsole, layout: dict[str, Any]) -> ScriptResult | None:
    """从店内走到可互动格并打开商店菜单；已在菜单时不移动。"""
    if console.scene() == "shop_items":
        return None
    if console.scene() != "shop":
        return ScriptResult(ok=False, code="wrong_scene", data={"scene": console.scene()})
    stand = layout["stand"]
    result = walk_to(console, int(stand["x"]), int(stand["y"]))
    if not result.ok:
        return result
    result = face_direction(console, stand["facing"])
    if not result.ok:
        return result
    run = ScriptRun(
        console,
        budget=0,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=ScriptPolicy(wait=StableWait(minimum_frames=64, abort_on_timeout=True)),
    )
    try:
        run.press_screen("a")
        run.wait_for(lambda text: console.scene() == "shop_items", expect="商店菜单")
    except Abort as failure:
        return run.finish(ok=False, code=failure.code.value, extra={"reason": failure.reason})
    return None


COUNT_LIMIT = 99
"""单次买卖的数量上限（游戏数量框上限）。"""


def _layout(console: WorldConsole) -> dict[str, Any] | None:
    """当前图的商店白名单项；白名单外 → None（`unsupported_map`）。"""
    return SHOP_LAYOUTS.get(str(console.map_id()))


def _goods(layout: dict[str, Any]) -> dict[str, int]:
    return {g["item"]: g["price"] for g in layout.get("goods", [])}


def _new_run(console: WorldConsole) -> ScriptRun:
    return ScriptRun(
        console,
        budget=1,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
        policy=field_policy(),
    )


def buy_item(console: WorldConsole, item: str, count: int) -> ScriptResult:
    """买：白名单店 → 在售 → 数量/预算前置 → `shop_buy`（光标/数量/确认代答）→
    终态对账（money0−money1==price×count 且 stock 增量==count）。"""
    layout = _layout(console)
    if layout is None:
        return ScriptResult(ok=False, code="unsupported_map", data={"map_id": console.map_id()})
    if console.scene() not in {"shop", "shop_items"}:
        return ScriptResult(ok=False, code="wrong_scene", data={"scene": console.scene()})
    goods = _goods(layout)
    if item not in goods:
        return ScriptResult(ok=False, code="not_sold_here", data={"item": item})
    if not 1 <= count <= COUNT_LIMIT:
        return ScriptResult(ok=False, code="count_limit", data={"count": count})
    price = goods[item]
    money0 = console.money()
    if count * price > money0:
        return ScriptResult(
            ok=False,
            code="insufficient_funds",
            data={"item": item, "count": count, "price": price, "money": money0},
        )
    stock0 = console.bag_count(item)
    failed = _enter_shop(console, layout)
    if failed is not None:
        return failed
    inner = console.run_script("shop_buy", {"item": item, "quantity": count})
    if not inner.ok:
        return ScriptResult(
            ok=False,
            code="verify_failed",
            data={
                "item": item,
                "count": count,
                "inner_code": inner.code,
                "reason": inner.data.get("reason", ""),
            },
        )
    money1, stock1 = console.money(), console.bag_count(item)
    if money0 - money1 != price * count or stock1 - stock0 != count:
        return ScriptResult(
            ok=False,
            code="verify_failed",
            data={
                "item": item,
                "count": count,
                "spent": money0 - money1,
                "expected_spent": price * count,
                "gained": stock1 - stock0,
            },
        )
    return ScriptResult(
        ok=True,
        code="ok",
        data={
            "item": item,
            "count": count,
            "spent": money0 - money1,
            "remaining_money": money1,
            "stock": stock1,
        },
    )


def sell_item(console: WorldConsole, item: str, count: int) -> ScriptResult:
    """卖：白名单店 → 背包有货/数量足 → `shop_sell` → 终态对账（money 增量==卖价×count，
    卖价 = 买价一半，Gen1 规则）。"""
    layout = _layout(console)
    if layout is None:
        return ScriptResult(ok=False, code="unsupported_map", data={"map_id": console.map_id()})
    if console.scene() not in {"shop", "shop_items"}:
        return ScriptResult(ok=False, code="wrong_scene", data={"scene": console.scene()})
    if not 1 <= count <= COUNT_LIMIT:
        return ScriptResult(ok=False, code="count_limit", data={"count": count})
    stock0 = console.bag_count(item)
    if stock0 == 0:
        return ScriptResult(ok=False, code="not_in_bag", data={"item": item})
    if count > stock0:
        return ScriptResult(
            ok=False,
            code="insufficient_stock",
            data={"item": item, "stock": stock0, "count": count},
        )
    money0 = console.money()
    identifier = item_id(item)
    price = item_price(console.rom, identifier) if identifier is not None else None
    if price is None:
        return ScriptResult(ok=False, code="not_sold_here", data={"item": item})
    unit = price // 2
    failed = _enter_shop(console, layout)
    if failed is not None:
        return failed
    inner = console.run_script("shop_sell", {"item": item, "quantity": count})
    if not inner.ok:
        return ScriptResult(
            ok=False,
            code="verify_failed",
            data={
                "item": item,
                "count": count,
                "inner_code": inner.code,
                "reason": inner.data.get("reason", ""),
            },
        )
    money1, stock1 = console.money(), console.bag_count(item)
    if money1 - money0 != unit * count:
        return ScriptResult(
            ok=False,
            code="verify_failed",
            data={
                "item": item,
                "count": count,
                "earned": money1 - money0,
                "expected_earned": unit * count,
            },
        )
    return ScriptResult(
        ok=True,
        code="ok",
        data={
            "item": item,
            "count": count,
            "earned": money1 - money0,
            "remaining_money": money1,
            "stock": stock1,
        },
    )


__all__ = ["buy_item", "sell_item"]
