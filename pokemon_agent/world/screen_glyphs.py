"""屏幕图块的上下文判据：数字九与擦除黑块、标题 Logo。"""


def has_text_neighbor(row: list[int], column: int) -> bool:
    """左右邻格至少一个是空格、文字或边框图块；不把另一个黑块当文字。"""
    return any(
        0 <= neighbor < len(row) and 0x79 <= row[neighbor] <= 0xFE
        for neighbor in (column - 1, column + 1)
    )


def erased_tiles(tiles: list[list[int]]) -> int:
    """计数没有字表邻居的 0xFF；调用方须给完整屏幕图块。"""
    return sum(
        tile == 0xFF and not has_text_neighbor(row, column)
        for row in tiles
        for column, tile in enumerate(row)
    )


def title_logo(tiles: list[list[int]]) -> bool:
    """标题 Logo 第一行固定连续十六图块，独立于战斗与地图残留变量。"""
    return tiles[1][2:18] == list(range(0x80, 0x90))


def graphic_only(tiles: list[list[int]]) -> bool:
    """无文字图块且无完整普通框时，图形页上的 HUD/边框别名不算文字。"""
    if any(tile >= 0x80 for row in tiles for tile in row):
        return False
    for top, values in enumerate(tiles):
        for left, tile in enumerate(values):
            if tile != 0x79:
                continue
            for right in range(left + 1, len(values)):
                if values[right] != 0x7B:
                    continue
                if any(row[left] == 0x7D and row[right] == 0x7E for row in tiles[top + 1 :]):
                    return False
    return True
