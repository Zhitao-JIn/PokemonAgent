"""`WorldConsole` 的两个测试替身：`FakeConsole`（帧序列）与 `StubConsole`（位移 / 店内）。

**为什么在这**：这两个类原先分别定义在 `world/scripts/test_script_run.py` 与
`mcp_servers/test_mcp_script_tools.py` 里，被别的测试文件跨文件 import（评测、P5 选动作测试）。
测试文件之间不许互相 import，共用的替身一律放这里。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.ram import W_COLLISION_PTR


class FakeMemory:
    """普通已载入地图的内存替身，其余地址默认0，可按十进制地址字符串覆盖。"""

    def __init__(self, **vals: int) -> None:
        self._v = {int(address): value for address, value in vals.items()}
        self._v.setdefault(W_COLLISION_PTR, 1)

    def __getitem__(self, addr: int) -> int:
        return self._v.get(addr, 0)


class FakeConsole:
    """`WorldConsole` 替身：按键推进帧序列，map_id / 坐标可脚本化。"""

    def __init__(
        self, frames: list[ScreenText], *, map_id: int = 12, pos: PlaceInWorld | None = None
    ) -> None:
        self._frames = list(frames)
        self._i = 0
        self.memory = FakeMemory()
        self.rom = b""
        self._map_id = map_id
        self._pos = pos or PlaceInWorld(map_id=12, x=13, y=8)

    def press(self, key: str) -> None:
        if self._i < len(self._frames) - 1:
            self._i += 1

    def tick(self, frames: int) -> None:  # noqa: ARG002 —— 测试帧不随时间变化
        pass

    def read(self) -> ScreenText:
        return self._frames[self._i]

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return self._pos

    def facing(self) -> str:
        return ""

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


class StubConsole:
    """最小 WorldConsole 替身：可编程位移与店内状态。"""

    def __init__(self, *, walkable: set[tuple[int, int]] | None = None) -> None:
        self.x, self.y = 15, 8
        self._walkable = walkable or set()
        self._facing = "south"
        self.money_value = 3000
        self.bag: dict[str, int] = {}
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(key, (0, 0))
        facing = {"up": "north", "down": "south", "left": "west", "right": "east"}.get(key)
        if facing:
            self._facing = facing  # 真机语义：按方向键即转身
        nx, ny = self.x + dx, self.y + dy
        if (nx, ny) in self._walkable:
            self.x, self.y = nx, ny

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> Any:  # noqa: ANN401
        from pokemon_agent.world import ScreenText

        return ScreenText()

    def map_id(self) -> int:
        return 42

    def pos(self) -> Any:  # noqa: ANN401
        from pokemon_agent.world import PlaceInWorld

        return PlaceInWorld(map_id=42, x=self.x, y=self.y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:  # noqa: ARG002
        return None

    def is_grass(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def is_npc(self, x: int, y: int) -> bool:  # noqa: ARG002
        return False

    def scene(self) -> str:
        return "shop_items"

    def money(self) -> int:
        return self.money_value

    def bag_count(self, item: str) -> int:
        return self.bag.get(item, 0)

    def run_script(self, name: str, args: dict[str, str | int]) -> Any:  # noqa: ANN401
        from pokemon_agent.world.scripts import ScriptResult
        from pokemon_agent.world.scripts.engine import SHOP_LAYOUTS

        item, qty = str(args["item"]), int(args["quantity"])
        price = next(
            g["price"] for g in SHOP_LAYOUTS[str(self.map_id())]["goods"] if g["item"] == item
        )
        if name == "shop_buy":
            self.money_value -= price * qty
            self.bag[item] = self.bag.get(item, 0) + qty
        else:
            self.money_value += price // 2 * qty
            self.bag[item] = self.bag.get(item, 0) - qty
        return ScriptResult(ok=True, code="ok")
