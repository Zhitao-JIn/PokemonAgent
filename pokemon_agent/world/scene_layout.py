"""场景分类的图块证据：无地图空屏、开场画像及尚未显示光标的战斗菜单框。"""

from .interface import Memory
from .ram import map_settled
from .screen_glyphs import erased_tiles


def is_transition(tiles: list[list[int]], screen: str, memory: Memory) -> bool:
    """过场须有整屏空白、无已载入地图或独立开场画像的证据；地图黑边不算。"""
    if erased_tiles(tiles) >= 20:
        return True
    if all(tile == 0x7F for row in tiles for tile in row):
        return True
    if screen:
        return False
    if not map_settled(memory):
        return True
    return all(
        tile == ((column - 6) * 7 + row - 4 if 4 <= row < 11 and 6 <= column < 13 else 0x7F)
        for row, values in enumerate(tiles)
        for column, tile in enumerate(values)
    )


def has_battle_menu_frame(tiles: list[list[int]]) -> bool:
    """战斗中的背包大框或招式框即是菜单；只读边界，不补造选项与光标。"""
    large = tiles[2][4] == 0x79 and tiles[2][19] == 0x7B and tiles[12][4] == 0x7D
    moves = all(tiles[row][4] == tiles[row][19] == 0x7C for row in range(13, 17))
    return large or moves
