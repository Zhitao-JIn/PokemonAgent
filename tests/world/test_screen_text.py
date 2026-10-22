"""屏幕文字的用法示范：**RAM 档感知也读得出对话、选项与光标**。

`world/screen_text.py` 把 20×18 的 tile 缓冲按英文版《红》字表解码。
这里用手写的 tile 画面（与真机 dump 同形）钉住四种布局：底部对话框、竖排菜单、
战斗 2×2 菜单、以及两词名的背包列表（不能被切开）。
"""

from __future__ import annotations

from pokemon_agent.world.ram import W_TILEMAP
from pokemon_agent.world.screen_text import CHARMAP, W_IS_IN_BATTLE, read_screen_text

_TILE = {text: tile for tile, text in CHARMAP.items()} | {
    "LV": 0x6E,
    "HP": 0x71,
    "BAR[": 0x62,
    "BAR8": 0x6B,
    "BAR0": 0x63,
    "BAR]": 0x6C,
}
_BOX = {"┌": 0x79, "─": 0x7A, "┐": 0x7B, "│": 0x7C, "└": 0x7D, "┘": 0x7E, "·": 0x00}


def test_unboxed_numbers_keep_real_nines_with_text_neighbors() -> None:
    memory = _Memory({0: " 99 ".ljust(20)})

    text = read_screen_text(memory)

    assert "99" in text.screen


def test_shop_prices_remain_readable_while_the_cursor_is_erased() -> None:
    from pokemon_agent.world.interface import Facts
    from pokemon_agent.world.screen_text import overlay_of

    mem = _Memory(
        {
            0: "┌─MONEY─┐···········",
            1: "│  ¥1500│···········",
            2: "└───────┘···········",
            3: "····┌──────────────┐",
            4: "····│ POKé BALL    │",
            5: "····│         ¥200 │",
            6: "····│ ANTIDOTE     │",
            7: "····│         ¥100 │",
            8: "····└──────────────┘",
        }
    )

    text = read_screen_text(mem)

    assert text.options == ["POKé BALL", "ANTIDOTE"]
    assert text.option_grid == [["POKé BALL"], ["ANTIDOTE"]]
    assert text.option_details == ["¥200", "¥100"]
    assert text.cursor == "" and text.cursor_cell is None and not text.has_cursor
    assert overlay_of(text) is Facts.Overlay.CHOICE


class _Memory:
    """按地址取字节的假内存：屏幕行从 `rows` 来，其余地址为 0。"""

    def __init__(self, rows: dict[int, str], in_battle: bool = False, battle_hp: int = 0) -> None:
        self._bytes: dict[int, int] = {W_IS_IN_BATTLE: int(in_battle)}
        self._bytes.update({0xD015: battle_hp >> 8, 0xD016: battle_hp & 255})
        for row in range(18):
            tiles = _encode(rows.get(row, "·" * 20))
            assert len(tiles) == 20, f"row {row} is {len(tiles)} tiles"
            for col, tile in enumerate(tiles):
                self._bytes[W_TILEMAP + row * 20 + col] = tile

    def __getitem__(self, address: int) -> int:
        return self._bytes.get(address, 0)


def test_battle_switch_scene_is_independent_of_the_current_pokemon_hp() -> None:
    from pokemon_agent.world.interface import TaskScene
    from pokemon_agent.world.scene import classify_scene

    rows = {
        12: "┌──────────────────┐",
        14: "│Bring out which   │",
        16: "│POKéMON?          │",
        17: "└──────────────────┘",
    }
    alive = _Memory(rows, in_battle=True, battle_hp=16)
    fainted = _Memory(rows, in_battle=True, battle_hp=0)

    alive_scene = classify_scene(read_screen_text(alive), alive)
    fainted_scene = classify_scene(read_screen_text(fainted), fainted)

    assert alive_scene is TaskScene.BATTLE_SWITCH
    assert fainted_scene is TaskScene.BATTLE_SWITCH


def _encode(text: str) -> list[int]:
    """一行文字 → tile；`é` 与 `PK`/`MN` 这类单 tile 多字符的写成 `{PK}`。"""
    tiles, i = [], 0
    while i < len(text):
        if text[i] == "{":
            j = text.index("}", i)
            tiles.append(_TILE[text[i + 1 : j]])
            i = j + 1
            continue
        tiles.append(_BOX.get(text[i], _TILE.get(text[i], 0x00)))
        i += 1
    return tiles


def test_bottom_box_text_is_the_dialog() -> None:
    mem = _Memory(
        {
            12: "┌──────────────────┐",
            14: "│Wild RATTATA      │",
            16: "│appeared!        ▼│",
            17: "└──────────────────┘",
        },
        in_battle=True,
    )

    text = read_screen_text(mem)

    assert text.dialog_text == "Wild RATTATA appeared!"
    assert text.options == [] and text.cursor == ""
    assert text.in_battle


def test_vertical_menu_lists_every_option_and_the_cursor() -> None:
    rows = {0: "··········┌────────┐"}
    labels = ["", "▶POKéDEX", "", " POKéMON", "", " ITEM", "", " EXIT"] + [""] * 6
    for r, label in enumerate(labels, start=1):
        rows[r] = "··········│" + label.ljust(8) + "│"
    rows[15] = "··········└────────┘"

    text = read_screen_text(_Memory(rows))

    assert text.options == ["POKéDEX", "POKéMON", "ITEM", "EXIT"]
    assert text.cursor == "POKéDEX"
    assert text.option_grid == [["POKéDEX"], ["POKéMON"], ["ITEM"], ["EXIT"]]
    assert len(text.option_grid) == 4 and text.cursor_cell == (0, 0)


def test_battle_menu_splits_into_two_columns() -> None:
    mem = _Memory(
        {
            12: "┌───────┌──────────┐",
            13: "│       │          │",
            14: "│       │ FIGHT▶{PK}{MN} │",
            15: "│       │          │",
            16: "│       │ ITEM  RUN│",
            17: "└───────└──────────┘",
        },
        in_battle=True,
    )

    text = read_screen_text(mem)

    assert text.options == ["FIGHT", "PKMN", "ITEM", "RUN"]
    assert text.cursor == "PKMN"
    assert text.option_grid == [["FIGHT", "PKMN"], ["ITEM", "RUN"]]
    assert text.cursor_cell == (0, 1)
    assert (
        len(text.option_grid) == 2
        and all(len(row) == 2 for row in text.option_grid)
        and text.cursor_cell == (0, 1)
    )


def test_two_word_item_names_are_not_split() -> None:
    rows = {1: "····┌──────────────┐"}
    body = ["", "▶TOWN MAP", "", " POKé BALL", "", " CANCEL"]
    for r, label in enumerate(body, start=2):
        rows[r] = "····│" + label.ljust(14) + "│"
    rows[8] = "····└──────────────┘"

    text = read_screen_text(_Memory(rows))

    assert text.options == ["TOWN MAP", "POKé BALL", "CANCEL"]
    assert text.cursor == "TOWN MAP"


def test_a_menu_laid_over_the_dialog_box_does_not_leak_into_the_dialog() -> None:
    mem = _Memory(
        {
            11: "···········┌───────┐",
            12: "┌──────────│▶STATS │",
            13: "│          │       │",
            14: "│Choose a P│ SWITCH│",
            15: "│          │       │",
            16: "│          │ CANCEL│",
            17: "└──────────────────┘",
        }
    )

    text = read_screen_text(mem)

    assert text.dialog_text == "Choose a P"
    assert text.options == ["STATS", "SWITCH", "CANCEL"]
    assert text.covered


def test_prices_and_quantities_hang_on_the_item_above() -> None:
    rows = {2: "····┌──────────────┐"}
    body = ["", "▶POKé BALL", "         ¥200", " ANTIDOTE", "         ×  3", " CANCEL"]
    for r, label in enumerate(body, start=3):
        rows[r] = "····│" + label.ljust(14) + "│"
    rows[9] = "····└──────────────┘"

    text = read_screen_text(_Memory(rows))

    assert text.options == ["POKé BALL", "ANTIDOTE", "CANCEL"]
    assert text.option_details == ["¥200", "× 3", ""]
    assert text.covered


def test_a_cursor_outside_any_box_marks_the_frame_uncovered() -> None:
    mem = _Memory({0: "   BULBASAUR  10    ", 1: "▶   ········· 21/ 32"})

    text = read_screen_text(mem)

    assert text.options == [] and text.cursor == ""
    assert not text.covered


def test_a_plain_dialog_box_is_a_strict_dialog() -> None:
    mem = _Memory(
        {
            12: "┌──────────────────┐",
            14: "│Hey! You came from│",
            16: "│PALLET TOWN?     ▼│",
            17: "└──────────────────┘",
        }
    )

    text = read_screen_text(mem)

    assert text.strict_dialog
    assert not text.has_cursor and not text.quantity_box


def test_a_dialog_with_another_box_on_screen_is_not_a_strict_dialog() -> None:
    mem = _Memory(
        {
            12: "┌──────────────────┐",
            14: "│What?   ┌────────┐│",
            16: "│        │BOX No.1││",
            17: "└────────└────────┘┘",
        }
    )

    text = read_screen_text(mem)

    assert text.dialog_text.startswith("What?")
    assert not text.strict_dialog


def test_a_quantity_box_is_seen_even_without_a_cursor() -> None:
    mem = _Memory(
        {
            9: "····│··┌───────────┐",
            10: "····│·B│×02    ¥400│",
            11: "····│··└───────────┘",
            12: "┌──────────────────┐",
            14: "│Take your time.   │",
            17: "└──────────────────┘",
        }
    )

    text = read_screen_text(mem)

    assert text.quantity_box and not text.has_cursor
    assert text.options == [], "数量框切不出选项，靠 quantity_box 给宽掩码"
    assert not text.strict_dialog


def test_a_bag_quantity_line_is_not_a_quantity_box() -> None:
    rows = {
        2: "····┌──────────────┐",
        3: "····│▶POTION       │",
        4: "····│         × 3  │",
        5: "····│ POKé BALL    │",
        6: "····│         ×12  │",
        7: "····│ CANCEL       │",
        8: "····└──────────────┘",
    }

    text = read_screen_text(_Memory(rows))

    assert not text.quantity_box, "两位数的持有数 `×12` 前面是空白，不是数量框"
    assert text.option_details == ["× 3", "×12", ""]


def test_the_party_list_maps_the_health_row_cursor_to_the_name() -> None:
    mem = _Memory(
        {
            0: "   BULBASAUR {LV}7     ",
            1: "▶   {HP}{BAR[}{BAR8}{BAR8}{BAR8}{BAR0}{BAR0}{BAR0}{BAR]} 25/ 25",
            2: "   PIDGEY    {LV}3     ",
            3: "    {HP}{BAR[}{BAR8}{BAR8}{BAR8}{BAR8}{BAR8}{BAR8}{BAR]} 15/ 15",
            12: "┌──────────────────┐",
            14: "│Choose a POKéMON. │",
            17: "└──────────────────┘",
        },
        in_battle=True,
    )

    text = read_screen_text(mem)

    assert text.has_cursor and text.covered
    assert text.options == ["BULBASAUR", "PIDGEY"]
    assert text.option_grid == [["BULBASAUR"], ["PIDGEY"]]
    assert text.cursor == "BULBASAUR" and text.cursor_cell == (0, 0)
    assert "BULBASAUR :L7" in text.screen
    assert "▶   HP:[███   ] 25/ 25" in text.screen, "血条按填充渲染，光标在第一只那一行"


def test_level_lines_do_not_make_a_boxed_list_uncovered() -> None:
    rows = {
        2: "····┌──────────────┐",
        3: "····│▶BULBASAUR    │",
        4: "····│         {LV}10  │",
        5: "····│ PIDGEY       │",
        6: "····│         {LV}5   │",
        7: "····│ CANCEL       │",
        8: "····└──────────────┘",
    }

    text = read_screen_text(_Memory(rows))

    assert text.options == ["BULBASAUR", "PIDGEY", "CANCEL"]
    assert text.covered


def test_only_a_strict_dialog_narrows_the_keys_to_a() -> None:
    from pokemon_agent.world import OVERLAY_ACTIONS, Facts, overlay_of

    box = {12: "┌──────────────────┐", 17: "└──────────────────┘"}
    dialog = read_screen_text(_Memory({**box, 14: "│Hey!              │"}))
    party = read_screen_text(
        _Memory({1: "▶   BULBASAUR       ", 14: "│Choose a POKéMON. │", 12: "┌" + "─" * 18 + "┐"})
    )

    assert OVERLAY_ACTIONS[overlay_of(dialog)] == ("a",)
    assert overlay_of(party) is Facts.Overlay.CHOICE
    assert {"up", "down", "b"} <= set(OVERLAY_ACTIONS[overlay_of(party)])
