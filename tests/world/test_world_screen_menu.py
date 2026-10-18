"""屏幕菜单：竖排菜单的逐行读取与光标格、战斗 2×2 菜单的分列。"""

from __future__ import annotations

from pokemon_agent.world.ram import SCREEN_COLS, SCREEN_ROWS, W_TILEMAP
from pokemon_agent.world.screen_text import CHARMAP, W_IS_IN_BATTLE, read_screen_text

_TILE = {text: tile for tile, text in CHARMAP.items()}
_BOX = {"┌": 0x79, "─": 0x7A, "┐": 0x7B, "│": 0x7C, "└": 0x7D, "┘": 0x7E, "·": 0x00}
BLANK = 0x00

VERTICAL_ROWS = {
    0: "··········┌────────┐",
    1: "··········│▶POKEMON│",
    2: "··········│ ITEM   │",
    3: "··········│ SAVE   │",
    4: "··········└────────┘",
}
SECOND_ROW_CURSOR_ROWS = {
    **VERTICAL_ROWS,
    1: "··········│ POKEMON│",
    2: "··········│▶ITEM   │",
}
BATTLE_ROWS = {
    12: "┌───────┌──────────┐",
    13: "│       │          │",
    14: "│       │▶FIGHT {PK}{MN} │",
    15: "│       │          │",
    16: "│       │ ITEM  RUN│",
    17: "└───────└──────────┘",
}


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

    def __init__(self, rows: dict[int, str], values: dict[int, int] | None = None) -> None:
        self._bytes: dict[int, int] = dict(values or {})
        for row in range(SCREEN_ROWS):
            for column in range(SCREEN_COLS):
                self._bytes[W_TILEMAP + row * SCREEN_COLS + column] = BLANK
        for row, text in rows.items():
            for column, tile in enumerate(_encode(text)):
                self._bytes[W_TILEMAP + row * SCREEN_COLS + column] = tile

    def __getitem__(self, address: int) -> int:
        return self._bytes.get(address, 0)


def test_vertical_menu_reads_every_row_and_marks_cursor_cell() -> None:
    text = read_screen_text(Mem(VERTICAL_ROWS))

    assert text.option_grid == [["POKEMON"], ["ITEM"], ["SAVE"]]
    assert text.cursor_cell == (0, 0)
    assert text.covered is True


def test_cursor_on_second_row_reports_that_cell() -> None:
    text = read_screen_text(Mem(SECOND_ROW_CURSOR_ROWS))

    assert text.cursor_cell == (1, 0)


def test_battle_menu_reads_a_two_by_two_grid() -> None:
    mem = Mem(BATTLE_ROWS, {W_IS_IN_BATTLE: 1})

    assert read_screen_text(mem).option_grid == [["FIGHT", "PKMN"], ["ITEM", "RUN"]]
