"""导航 / 场所类脚本单测（P4 第二批）：exit_map / heal_at_center。

**对得上谁**：PLAN 附录 A #6（exit_map）与 #14（heal_at_center）的单测列。
`NavConsole` 模拟可走格 + 出口触发；`HealConsole` 在前者基础上补护士对话序列
与队伍 HP 内存（`PartyMem` 按 `healed` 标志返回 HP）。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.interface import BUTTON_FACING
from pokemon_agent.world.ram import (
    W_PARTY_COUNT,
    W_PARTY_MON1_HP,
    W_PARTY_SPECIES,
)
from pokemon_agent.world.scripts import engine as scripts_engine
from pokemon_agent.world.scripts.navigation import exit_map, heal_at_center

MAP = 12
DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


class NavConsole:
    """可走格 + 出口触发：方向键在可走格上位移；`warp_on` 里的方向踩中即换图
    （北→1 / 其它→0）；`blocked_dirs` 方向被挡（不位移不换图）。"""

    def __init__(
        self,
        walkable: set[tuple[int, int]],
        *,
        start: tuple[int, int],
        map_id: int = MAP,
        warp_on: set[str] | None = None,
        blocked_dirs: set[str] | None = None,
    ) -> None:
        self._walkable = set(walkable)
        self.x, self.y = start
        self._map_id = map_id
        self._warp_on = set(warp_on or set())
        self._blocked_dirs = set(blocked_dirs or set())
        self._facing = "south"
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        if key in BUTTON_FACING:
            self._facing = BUTTON_FACING[key]
            if key in self._blocked_dirs:
                return
            dx, dy = DELTA[key]
            nx, ny = self.x + dx, self.y + dy
            if key in self._warp_on:
                self._map_id = 1 if key == "up" else 0
            elif (nx, ny) in self._walkable:
                self.x, self.y = nx, ny

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        return ScreenText()

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

    def scene(self) -> str:
        return "walk"

    def money(self) -> int:
        return 0

    def bag_count(self, item: str) -> int:  # noqa: ARG002
        return 0

    def run_script(self, name: str, args: dict[str, str | int]) -> Any:  # noqa: ARG002
        raise AssertionError("导航测试不应组合调用别的脚本")


# ---- exit_map（附录 A #6）----


def _ground() -> set[tuple[int, int]]:
    return {(x, y) for x in range(0, 30) for y in range(0, 30)}


def test_exit_map_warp_success() -> None:
    """① 朝触发方向走 → 换图成功（map 12 北出口 → map 1）。"""
    console = NavConsole(_ground(), start=(15, 8), map_id=12, warp_on={"up"})
    res = exit_map(console)
    assert res.ok and res.code == "ok"
    assert res.data["to_map"] == 1


def test_exit_map_stops_when_path_hits_an_obstacle() -> None:
    """无出口的有限地面最终被挡，应停止并报告 blocked。"""
    console = NavConsole(_ground(), start=(15, 8), map_id=12, warp_on=set())
    res = exit_map(console)
    assert not res.ok and res.code == "blocked"


def test_exit_map_unsupported_map() -> None:
    """map 不在白名单 → unsupported_map。"""
    console = NavConsole(_ground(), start=(15, 8), map_id=999)
    res = exit_map(console)
    assert not res.ok and res.code == "unsupported_map"


def test_exit_map_door_warp_blocked() -> None:
    """④ 门 warp 去门口途中被挡 → 透传 blocked。"""
    # 注入一张只有门 warp 的假地图
    fake = {"door_warps": [{"x": 5, "y": 5, "dir": "up"}], "edge_exits": []}
    scripts_engine.WARPS["99"] = fake
    try:
        # 只有 (5,5) 可走、起点 (5,8) → walk_to(5,5) 够不到 → blocked
        console = NavConsole({(5, 5)}, start=(5, 8), map_id=99)
        res = exit_map(console)
        assert not res.ok and res.code == "blocked"
    finally:
        del scripts_engine.WARPS["99"]


# ---- heal_at_center（附录 A #14）----


class PartyMem:
    """按 `healed` 标志返回队伍 HP（heal 确认 YES 后变满）。"""

    def __init__(self, console: HealConsole) -> None:
        self._c = console

    def __getitem__(self, addr: int) -> int:
        if addr == W_PARTY_COUNT:
            return 1
        if addr == W_PARTY_SPECIES:
            return 1
        base = W_PARTY_MON1_HP
        hp = 20 if self._c.healed else 5
        if addr == base:
            return hp & 0xFF
        if addr == base + 1:
            return (hp >> 8) & 0xFF
        if addr == base + 0x20:
            return 5  # level
        if addr == base + 0x21:
            return 20 & 0xFF
        if addr == base + 0x22:
            return (20 >> 8) & 0xFF
        if addr == base + 3:
            return 0  # status
        return 0


class HealConsole:
    """可走格 + 护士对话序列 + 队伍 HP（按 healed 标志）。"""

    def __init__(
        self,
        script: list[dict[str, Any]],
        *,
        walkable: set[tuple[int, int]],
        start: tuple[int, int],
        map_id: int = 41,
    ) -> None:
        self._walkable = set(walkable)
        self.x, self.y = start
        self._map_id = map_id
        self._script = script
        self.presses = 0  # 只数 a 键（对话推进）；走路方向键不推进脚本
        self._facing = "south"
        self._healed = False
        self._at_choice = False
        self.rom = b""

    @property
    def healed(self) -> bool:
        """PartyMem 读 HP 用。"""
        return self._healed

    @property
    def memory(self) -> PartyMem:
        return PartyMem(self)

    def press(self, key: str) -> None:
        if key in BUTTON_FACING:
            self._facing = BUTTON_FACING[key]
            dx, dy = DELTA[key]
            nx, ny = self.x + dx, self.y + dy
            if (nx, ny) in self._walkable:
                self.x, self.y = nx, ny
            return
        if key == "a":
            self.presses += 1
            if self._at_choice:
                self._healed = True

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        if self.presses > 0 and self._script:
            over = self._script[min(self.presses - 1, len(self._script) - 1)]
        else:
            over = {}
        self._at_choice = bool(over.get("options") and "YES" in over.get("options", []))
        return ScreenText(
            in_battle=over.get("in_battle", False),
            dialog_text=over.get("dialog_text", ""),
            options=over.get("options", []),
            has_cursor=over.get("has_cursor", False),
        )

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

    def scene(self) -> str:
        t = self.read()
        if t.in_battle:
            return "battle"
        if t.dialog_text:
            return "dialog"
        return "walk"

    def money(self) -> int:
        return 0

    def bag_count(self, item: str) -> int:  # noqa: ARG002
        return 0

    def run_script(self, name: str, args: dict[str, str | int]) -> Any:  # noqa: ARG002
        raise AssertionError("heal 测试不应组合调用别的脚本")


def _pokecenter_walkable() -> set[tuple[int, int]]:
    # 竖直走廊 (3,2..5)，护士 (3,1) 不可走
    return {(3, y) for y in range(2, 6)}


def test_heal_unsupported_map() -> None:
    """② map 非白名单 → unsupported_map（不动）。"""
    console = HealConsole([{}], walkable={(3, 2)}, start=(3, 5), map_id=12)
    res = heal_at_center(console)
    assert not res.ok and res.code == "unsupported_map"


def test_heal_full_flow_with_yes_no() -> None:
    """① 全流程：走到护士前→对话→确认 YES→回满 → ok。"""
    script = [
        {"dialog_text": "Welcome to the POKéMON CENTER!"},
        {"dialog_text": "Should I heal your pokémon?"},
        {
            "options": ["YES", "NO"],
            "has_cursor": True,
            "dialog_text": "Should I heal your pokémon?",
        },
        {"dialog_text": "OK! Your pokémon are healed!"},
        {"dialog_text": "Thank you!"},
        {},
    ]
    console = HealConsole(script, walkable=_pokecenter_walkable(), start=(3, 5), map_id=41)
    res = heal_at_center(console, max_steps=60)
    assert res.ok and res.code == "ok", res
    assert res.data["healed"] is True


def test_heal_verify_failed_when_not_full() -> None:
    """④ 队伍未全满（无 YES/NO、healed 未置位）→ verify_failed。"""
    script = [
        {"dialog_text": "Welcome!"},
        {"dialog_text": "Healing..."},
        {"dialog_text": "Thank you!"},
        {},
    ]
    console = HealConsole(script, walkable=_pokecenter_walkable(), start=(3, 5), map_id=41)
    res = heal_at_center(console, max_steps=60)
    assert not res.ok and res.code == "verify_failed"


def test_heal_still_talking() -> None:
    """对话推不完（预算内）→ still_talking。"""
    script = [{"dialog_text": f"句{i}"} for i in range(40)] + [{}]
    console = HealConsole(script, walkable=_pokecenter_walkable(), start=(3, 5), map_id=41)
    res = heal_at_center(console, max_steps=5)
    assert not res.ok and res.code == "still_talking"
