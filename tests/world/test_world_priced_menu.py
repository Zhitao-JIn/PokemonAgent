"""价格框：只有 MONEY 标题时读商品与价格；单项、无标题与框内边框图块都被拒绝。"""

from __future__ import annotations

from pokemon_agent.world.priced_menu import read_priced_menu
from pokemon_agent.world.ram import SCREEN_COLS, SCREEN_ROWS
from pokemon_agent.world.screen_text import CHARMAP

_TILE = {text: tile for tile, text in CHARMAP.items()}
_BOX = {"┌": 0x79, "─": 0x7A, "┐": 0x7B, "│": 0x7C, "└": 0x7D, "┘": 0x7E, "·": 0x00}
BLANK = 0x00

MONEY_ROWS = {
    0: "┌─MONEY─┐···········",
    1: "│  ¥300 │···········",
    2: "└───────┘···········",
    3: "····┌──────────────┐",
    4: "····│ POTION       │",
    5: "····│         ¥300 │",
    6: "····│ CANCEL       │",
    7: "····└──────────────┘",
}
"""`MONEY ¥300` 标题，下面是 POTION / ¥300 / CANCEL 的商品框。"""

NO_MONEY_ROWS = {**MONEY_ROWS, 0: "┌───────┐···········", 1: "│       │···········"}

SINGLE_ITEM_ROWS = {
    0: MONEY_ROWS[0],
    1: MONEY_ROWS[1],
    2: MONEY_ROWS[2],
    3: "····┌──────────────┐",
    4: "····│ CANCEL       │",
    5: "····└──────────────┘",
}


def _encode(text: str) -> list[int]:
    """一行文字 → tile。"""
    return [_BOX.get(character, _TILE.get(character, BLANK)) for character in text]


def _tiles(rows: dict[int, str]) -> list[list[int]]:
    """18×20 的图块屏，未写的格为空白。"""
    tiles = [[BLANK] * SCREEN_COLS for _ in range(SCREEN_ROWS)]
    for row, text in rows.items():
        for column, tile in enumerate(_encode(text)):
            tiles[row][column] = tile
    return tiles


def _render_text(tiles: list[int]) -> str:
    """假渲染器：按字表逐块转文字，字表外的块当空白，行尾空白去掉。"""
    return "".join(CHARMAP.get(tile, " ") for tile in tiles).strip()


def test_no_money_title_returns_empty() -> None:
    assert read_priced_menu(_tiles(NO_MONEY_ROWS), _render_text) == []


def test_priced_box_returns_items_with_prices_and_cancel() -> None:
    assert read_priced_menu(_tiles(MONEY_ROWS), _render_text) == [
        ("POTION", "¥300"),
        ("CANCEL", ""),
    ]


def test_single_item_box_is_refused() -> None:
    assert read_priced_menu(_tiles(SINGLE_ITEM_ROWS), _render_text) == []


def test_border_tile_inside_box_is_refused() -> None:
    tiles = _tiles(MONEY_ROWS)
    tiles[5][10] = 0x7D

    assert read_priced_menu(tiles, _render_text) == []
