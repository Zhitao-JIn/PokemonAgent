"""商店脚本单测（P4 第一批收官）：buy_item / sell_item。

**对得上谁**：PLAN 附录 A #12/#13 的单测列。`ShopConsole` 模拟店内世界：
白名单 map、SHOP_ITEMS 场合、现金/背包状态、脚本 `shop_buy` / `shop_sell` 的执行效果
（成功时按价格表记账，可注入走偏）。校验链全走脚本真实逻辑，不另起判定。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.scripts import ScriptResult
from pokemon_agent.world.scripts.shop import buy_item, sell_item

GOODS = [
    {"item": "POKé BALL", "price": 200},
    {"item": "POTION", "price": 300},
]


class ShopConsole:
    """店内替身：`inner_mode` 控制内层脚本的行为（"ok"=正常记账 / "abort"=走偏）。"""

    def __init__(
        self,
        *,
        map_id: int = 42,
        money: int = 3000,
        bag: dict[str, int] | None = None,
        scene: str = "shop_items",
        inner_mode: str = "ok",
    ) -> None:
        self._map_id = map_id
        self._money = money
        self._bag = dict(bag or {})
        self._scene = scene
        self._inner_mode = inner_mode
        self.memory: Any = _Mem()
        prices = bytearray(0x4700)
        prices[0x4608 + (11 - 1) * 3 : 0x4608 + (11 - 1) * 3 + 3] = bytes([0, 1, 0])
        prices[0x4608 + (20 - 1) * 3 : 0x4608 + (20 - 1) * 3 + 3] = bytes([0, 3, 0])
        self.rom = bytes(prices)
        self.x, self.y = 1, 5
        self._facing = "west"

    # ---- 商店状态 ----

    def apply_buy(self, item: str, quantity: int, price: int) -> None:
        self._money -= price * quantity
        self._bag[item] = self._bag.get(item, 0) + quantity

    def apply_sell(self, item: str, quantity: int, unit: int) -> None:
        self._money += unit * quantity
        self._bag[item] = self._bag.get(item, 0) - quantity

    # ---- WorldConsole ----

    def money(self) -> int:
        return self._money

    def bag_count(self, item: str) -> int:
        return self._bag.get(item, 0)

    def run_script(self, name: str, args: dict[str, str | int]) -> ScriptResult:
        item, qty = str(args["item"]), int(args["quantity"])
        if self._inner_mode != "ok":
            return ScriptResult(ok=False, code="step_timeout", data={"reason": "模拟走偏"})
        from pokemon_agent.world.scripts.engine import SHOP_LAYOUTS

        goods = SHOP_LAYOUTS[str(self._map_id)]["goods"]
        price = next(g["price"] for g in goods if g["item"] == item)
        if name == "shop_buy":
            self.apply_buy(item, qty, price)
        else:
            self.apply_sell(item, qty, price // 2)
        return ScriptResult(ok=True, code="ok")

    def scene(self) -> str:
        return self._scene

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def is_npc(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def press(self, key: str) -> None:  # noqa: ARG002 —— 内层按键由 run_script 替身吸收
        pass

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        return ScreenText()


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


# ---- buy_item（附录 A #12）----


def test_buy_success() -> None:
    """① 成功：扣款==price×count 且入库。"""
    console = ShopConsole(money=3000)
    res = buy_item(console, "POKé BALL", 5)
    assert res.ok and res.code == "ok"
    assert res.data["spent"] == 1000
    assert res.data["remaining_money"] == 2000
    assert res.data["stock"] == 5


def test_buy_not_sold_here() -> None:
    """② 不在售。"""
    console = ShopConsole()
    res = buy_item(console, "RARE CANDY", 1)
    assert not res.ok and res.code == "not_sold_here"


def test_buy_count_limit() -> None:
    """③ count>99 → count_limit。"""
    console = ShopConsole(money=999999)
    res = buy_item(console, "POKé BALL", 100)
    assert not res.ok and res.code == "count_limit"


def test_buy_insufficient_funds() -> None:
    """④ 钱不够 → insufficient_funds（不买）。"""
    console = ShopConsole(money=500)
    res = buy_item(console, "POKé BALL", 5)  # 1000 > 500
    assert not res.ok and res.code == "insufficient_funds"
    assert console.money() == 500, "前置拒绝不动账"
    assert console.bag_count("POKé BALL") == 0


def test_buy_inner_script_aborted_verify_failed() -> None:
    """⑤ 内层 `shop_buy` 走偏 → verify_failed。"""
    console = ShopConsole(money=3000, inner_mode="abort")
    res = buy_item(console, "POKé BALL", 5)
    assert not res.ok and res.code == "verify_failed"
    assert res.data["inner_code"] == "step_timeout"


def test_buy_unsupported_map() -> None:
    """白名单外 map → unsupported_map。"""
    console = ShopConsole(map_id=12)  # Route 1 不是商店
    res = buy_item(console, "POKé BALL", 1)
    assert not res.ok and res.code == "unsupported_map"


def test_buy_wrong_scene() -> None:
    """不在店内场合 → wrong_scene。"""
    console = ShopConsole(scene="walk")
    res = buy_item(console, "POKé BALL", 1)
    assert not res.ok and res.code == "wrong_scene"


# ---- sell_item（附录 A #13）----


def test_sell_success() -> None:
    """① 成功：收款==卖价×count（卖价=买价一半，ANTIDOTE 100 → 50）。"""
    console = ShopConsole(money=1000, bag={"ANTIDOTE": 3})
    res = sell_item(console, "ANTIDOTE", 2)
    assert res.ok and res.code == "ok"
    assert res.data["earned"] == 100  # 100//2 × 2
    assert res.data["remaining_money"] == 1100
    assert res.data["stock"] == 1


def test_sell_not_in_bag() -> None:
    """② 背包无此物 → not_in_bag。"""
    console = ShopConsole()
    res = sell_item(console, "ANTIDOTE", 1)
    assert not res.ok and res.code == "not_in_bag"


def test_sell_insufficient_stock() -> None:
    """③ count>stock → insufficient_stock。"""
    console = ShopConsole(bag={"ANTIDOTE": 1})
    res = sell_item(console, "ANTIDOTE", 2)
    assert not res.ok and res.code == "insufficient_stock"


def test_sell_verify_failed_on_amount_mismatch() -> None:
    """④ 到账金额不符 → verify_failed（注入错误到账）。"""
    console = ShopConsole(money=1000, bag={"ANTIDOTE": 3}, inner_mode="ok")

    def bad_sell(item: str, qty: int, unit: int) -> None:
        console._money += 200  # 到账错误（应为 50×2=100，实付 200）
        console._bag[item] = console._bag[item] - qty

    console.apply_sell = bad_sell  # type: ignore[method-assign]
    res = sell_item(console, "ANTIDOTE", 2)
    assert not res.ok and res.code == "verify_failed"
    assert res.data["earned"] == 200
    assert res.data["expected_earned"] == 100
