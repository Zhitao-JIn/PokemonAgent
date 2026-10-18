"""屏幕图块的上下文判据：字表邻居、擦除黑块、标题 Logo、纯图形页。"""

from pokemon_agent.world.screen_glyphs import (
    erased_tiles,
    graphic_only,
    has_text_neighbor,
    title_logo,
)

BLANK = 0x00
TEXT = 0x81
BLACK = 0xFF
LOGO = list(range(0x80, 0x90))


def _logo_tiles(shift: int) -> list[list[int]]:
    """第二行的 Logo 从 `2 + shift` 起排十六格；`shift=0` 才是标题 Logo。"""
    row = [BLANK] * 20
    row[2 + shift : 18 + shift] = LOGO
    return [[BLANK] * 20, row]


def test_has_text_neighbor_true_for_text_on_the_left() -> None:
    assert has_text_neighbor([TEXT, BLACK], 1) is True


def test_has_text_neighbor_true_for_text_on_the_right() -> None:
    assert has_text_neighbor([BLACK, TEXT], 0) is True


def test_a_black_block_neighbor_is_not_text() -> None:
    assert has_text_neighbor([BLACK, BLACK], 0) is False


def test_edge_column_counts_only_the_existing_neighbor() -> None:
    assert has_text_neighbor([BLACK, BLACK, TEXT], 0) is False
    assert has_text_neighbor([BLACK, TEXT], 0) is True


def test_erased_tiles_counts_black_blocks_without_text_neighbors() -> None:
    assert erased_tiles([[BLACK, BLANK], [BLANK, BLACK]]) == 2


def test_erased_tiles_ignores_black_blocks_next_to_text() -> None:
    assert erased_tiles([[BLACK, TEXT]]) == 0


def test_title_logo_needs_sixteen_consecutive_tiles_on_row_one() -> None:
    assert title_logo(_logo_tiles(0)) is True
    assert title_logo(_logo_tiles(1)) is False


def test_graphic_only_true_when_no_text_and_no_complete_box() -> None:
    assert graphic_only([[0x79, BLANK, 0x7B], [BLANK, 0x7D, BLANK]]) is True


def test_graphic_only_false_when_a_complete_box_exists() -> None:
    assert graphic_only([[0x79, BLANK, 0x7B], [0x7D, BLANK, 0x7E]]) is False


def test_graphic_only_false_when_any_text_tile_is_present() -> None:
    assert graphic_only([[BLANK, 0x80]]) is False
