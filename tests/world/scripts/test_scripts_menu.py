"""菜单类脚本单测（P4 第二批）：open_menu_to。

**对得上谁**：PLAN 附录 A #11（open_menu_to）的单测列。`MenuConsole` 模拟 start
菜单的光标移动与选中后场合跳转（`select_works=False` 用来逼出 wrong_scene）。
"""

from __future__ import annotations

from typing import Any

import pytest

from pokemon_agent.world import PlaceInWorld, ScreenText
from pokemon_agent.world.scripts.menu import open_menu_to

MAP = 12
ITEMS = ["POKéDEX", "POKéMON", "ITEM", "SAVE", "OPTION", "EXIT"]


class _Mem:
    def __getitem__(self, addr: int) -> int:  # noqa: ARG002
        return 0


class MenuConsole:
    """start 菜单：按 start 进菜单（光标默认 POKéDEX），up/down 移光标，a 选中。

    `select_works=False` 时选中不跳场合（留在 start_menu）→ 逼出 wrong_scene。
    """

    def __init__(self, *, select_works: bool = True) -> None:
        self._scene = "walk"
        self._cursor_idx = 0
        self._select_works = select_works
        self.x, self.y = 15, 8
        self._map_id = MAP
        self._facing = "south"
        self.memory: Any = _Mem()
        self.rom = b""

    def press(self, key: str) -> None:
        if key == "start" and self._scene == "walk":
            self._scene = "start_menu"
            self._cursor_idx = 0
            return
        if self._scene != "start_menu":
            return
        if key == "down":
            self._cursor_idx = min(len(ITEMS) - 1, self._cursor_idx + 1)
        elif key == "up":
            self._cursor_idx = max(0, self._cursor_idx - 1)
        elif key == "a":
            item = ITEMS[self._cursor_idx]
            if self._select_works:
                if item == "POKéMON":
                    self._scene = "party"
                elif item == "ITEM":
                    self._scene = "bag"
                # 其余项：保持 start_menu

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        if self._scene == "start_menu":
            return ScreenText(
                options=list(ITEMS),
                cursor=ITEMS[self._cursor_idx],
                has_cursor=True,
            )
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
        return self._scene

    def money(self) -> int:
        return 0

    def bag_count(self, item: str) -> int:  # noqa: ARG002
        return 0

    def run_script(self, name: str, args: dict[str, str | int]) -> Any:  # noqa: ARG002
        raise AssertionError("菜单测试不应组合调用别的脚本")


def test_open_menu_to_pokemon_submenu() -> None:
    """① start→POKéMON 子菜单成功（party）。"""
    console = MenuConsole()
    res = open_menu_to(console, "POKéMON")
    assert res.ok and res.code == "ok"
    assert res.data["scene"] == "party"


def test_open_menu_to_item_submenu() -> None:
    """① start→ITEM 子菜单成功（bag）。"""
    console = MenuConsole()
    res = open_menu_to(console, "ITEM")
    assert res.ok and res.code == "ok"
    assert res.data["scene"] == "bag"


def test_open_menu_to_wrong_scene_when_not_effective() -> None:
    """② 选中后仍在 start 菜单（光标走偏/未生效）→ wrong_scene。"""
    console = MenuConsole(select_works=False)
    res = open_menu_to(console, "POKéMON")
    assert not res.ok and res.code == "wrong_scene"
    assert res.data["scene"] == "start_menu"


def test_open_menu_to_rejected_bad_target() -> None:
    """target 不在菜单项里 → rejected。"""
    console = MenuConsole()
    res = open_menu_to(console, "NOT_A_MENU_ITEM")
    assert not res.ok and res.code == "rejected"


class ObservedMenuConsole(MenuConsole):
    """记录每次实际按键，可分别模拟开菜单失败与选中失败。"""

    def __init__(self, *, start_works: bool, select_works: bool) -> None:
        super().__init__(select_works=select_works)
        self.start_works = start_works
        self.keys: list[str] = []

    def press(self, key: str) -> None:
        self.keys.append(key)
        if key != "start" or self.start_works:
            super().press(key)


@pytest.mark.parametrize(
    ("target", "start_works", "select_works", "keys", "scene", "code"),
    [
        ("POKéMON", True, True, ["start", "down", "a"], "party", "ok"),
        ("ITEM", True, True, ["start", "down", "down", "a"], "bag", "ok"),
        ("POKéMON", True, False, ["start", "down", "a"], "start_menu", "wrong_scene"),
        ("POKéMON", False, True, ["start"], "walk", "wrong_scene"),
    ],
)
def test_menu_keeps_observations_on_every_exit_after_keys(
    target: str, start_works: bool, select_works: bool, keys: list[str], scene: str, code: str
) -> None:
    console = ObservedMenuConsole(start_works=start_works, select_works=select_works)

    result = open_menu_to(console, target)

    assert console.keys == keys
    assert len(result.observations) == len(keys)
    assert [observation.step for observation in result.observations] == list(
        range(1, len(keys) + 1)
    )
    assert all(
        observation.ram is not None and observation.settled for observation in result.observations
    )
    assert result.code == code and result.ok == (code == "ok")
    assert result.data == {"scene": scene, "target": target}
