"""道具的名字与价格。

名字表来自 `pret/pokered` 反汇编（`tables/items.json`），价格从 ROM 的 `ItemPrices` 读。

纯函数与只读常量，给接管脚本的前提校验与接管视图用。
"""

from __future__ import annotations

import json
from pathlib import Path

_NAMES: dict[int, str] = {
    int(k): v
    for k, v in json.loads(
        (Path(__file__).parent / "tables" / "items.json").read_text("utf-8")
    ).items()
}
ITEM_PRICES = 0x4608
"""ROM `ItemPrices`（bank 1）：每样 3 字节 BCD，按道具 id − 1 排。"""
LAST_REGULAR_ITEM = 0x53
"""普通道具的最后一个 id；之后是 HM / TM，价格不在 `ItemPrices` 里。"""
FIRST_HM, LAST_HM = 0xC4, 0xC8


def item_name(item_id: int) -> str:
    """道具 id → 名字；表里没有的写成 `ITEM_0x..`。"""
    return _NAMES.get(item_id, f"ITEM_0x{item_id:02X}")


def item_id(name: str) -> int | None:
    """名字 → 道具 id（大小写不敏感、`é` 与 `e` 视同）；认不出为 None。"""
    key = _fold(name)
    return next((i for i, n in _NAMES.items() if i and _fold(n) == key), None)


def item_price(rom: bytes, item: int) -> int | None:
    """道具单价；HM 为 0（不能卖），TM 与表外 id 为 None（价格不在 `ItemPrices`）。"""
    if FIRST_HM <= item <= LAST_HM:
        return 0
    if not 1 <= item <= LAST_REGULAR_ITEM:
        return None
    offset = ITEM_PRICES + (item - 1) * 3
    total = 0
    for byte in rom[offset : offset + 3]:
        total = total * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return total


def _fold(name: str) -> str:
    return " ".join(name.replace("é", "e").replace("É", "E").upper().split())


__all__ = ["item_id", "item_name", "item_price"]
