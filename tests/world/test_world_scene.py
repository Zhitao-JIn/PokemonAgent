"""场合分类：空屏、标题 Logo、开始菜单空框、命名键盘、战斗菜单与脚本初态判定。"""

from __future__ import annotations

import pytest

from pokemon_agent.world import TaskScene
from pokemon_agent.world.ram import SCREEN_COLS, SCREEN_ROWS, W_TILEMAP
from pokemon_agent.world.scene import W_IS_IN_BATTLE, at_start, classify_scene
from pokemon_agent.world.scene_layout import empty_menu_frame
from pokemon_agent.world.screen_text import CHARMAP, read_screen_text

_TILE = {text: tile for tile, text in CHARMAP.items()}
_BOX = {"┌": 0x79, "─": 0x7A, "┐": 0x7B, "│": 0x7C, "└": 0x7D, "┘": 0x7E, "·": 0x00}
BLANK = 0x00

BATTLE_ROWS = {
    12: "┌───────┌──────────┐",
    13: "│       │          │",
    14: "│       │▶FIGHT {PK}{MN} │",
    15: "│       │          │",
    16: "│       │ ITEM  RUN│",
    17: "└───────└──────────┘",
}
"""战斗 2×2 行动菜单，实心 ▶ 在 FIGHT 上。"""

ITEM_CURSOR_ROWS = {**BATTLE_ROWS, 14: "│       │ FIGHT {PK}{MN} │", 16: "│       │▶ITEM  RUN│"}
"""同一帧，▶ 移到 ITEM 上。"""


def _encode(text: str) -> list[int]:
    """一行文字 → tile；`{PK}` 这类单块多字符的整段查字表。"""
    tiles, i = [], 0
    while i < len(text):
        if text[i] == "{":
            end = text.index("}", i)
            tiles.append(_TILE[text[i + 1 : end]])
            i = end + 1
            continue
        tiles.append(_BOX.get(text[i], _TILE.get(text[i], BLANK)))
        i += 1
    return tiles


class Mem:
    """按地址取字节的假内存：屏幕 tile 从 `W_TILEMAP` 起写，未写的地址读 0。"""

    def __init__(
        self,
        rows: dict[int, str],
        values: dict[int, int] | None = None,
        fill: int = BLANK,
    ) -> None:
        self._bytes: dict[int, int] = dict(values or {})
        for row in range(SCREEN_ROWS):
            for column in range(SCREEN_COLS):
                self._bytes.setdefault(W_TILEMAP + row * SCREEN_COLS + column, fill)
        for row, text in rows.items():
            for column, tile in enumerate(_encode(text)):
                self._bytes[W_TILEMAP + row * SCREEN_COLS + column] = tile

    def __getitem__(self, address: int) -> int:
        return self._bytes.get(address, 0)


def _tiles(mem: Mem) -> list[list[int]]:
    return [
        [mem[W_TILEMAP + row * SCREEN_COLS + column] for column in range(SCREEN_COLS)]
        for row in range(SCREEN_ROWS)
    ]


def _scene(rows: dict[int, str], values: dict[int, int] | None = None) -> TaskScene:
    mem = Mem(rows, values)
    return classify_scene(read_screen_text(mem), mem)


def test_blank_screen_is_transition() -> None:
    mem = Mem({}, fill=0x7F)

    assert classify_scene(read_screen_text(mem), mem) is TaskScene.TRANSITION


def test_title_logo_row_is_title_scene() -> None:
    assert _scene({1: "··ABCDEFGHIJKLMNOP··"}) is TaskScene.TITLE


def test_empty_start_frame_is_start_menu() -> None:
    rows = {0: "··········┌────────┐", 15: "··········└────────┘"}
    rows.update({row: "··········│        │" for row in range(1, 15)})
    mem = Mem(rows)

    assert classify_scene(read_screen_text(mem), mem) is TaskScene.START_MENU
    assert empty_menu_frame(_tiles(mem), 0, 10, 15)


def test_alphabet_row_is_naming() -> None:
    assert _scene({1: "A B C D E F G H I"}) is TaskScene.NAMING


def test_battle_menu_with_fight_cursor_is_battle_menu() -> None:
    assert _scene(BATTLE_ROWS, {W_IS_IN_BATTLE: 1}) is TaskScene.BATTLE_MENU


def test_at_start_true_when_battle_cursor_on_fight() -> None:
    mem = Mem(BATTLE_ROWS, {W_IS_IN_BATTLE: 1})

    assert at_start(read_screen_text(mem), TaskScene.BATTLE_MENU) is True


def test_at_start_false_when_battle_cursor_on_item() -> None:
    mem = Mem(ITEM_CURSOR_ROWS, {W_IS_IN_BATTLE: 1})

    assert at_start(read_screen_text(mem), TaskScene.BATTLE_MENU) is False


def test_at_start_refuses_a_normal_scene() -> None:
    mem = Mem(BATTLE_ROWS, {W_IS_IN_BATTLE: 1})

    with pytest.raises(AssertionError):
        at_start(read_screen_text(mem), TaskScene.WALK)
