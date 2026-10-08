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
