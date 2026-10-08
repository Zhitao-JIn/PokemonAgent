"""非普通菜单的屏幕布局：按实际图块位置提取键盘、队伍和横向设置。"""

from collections.abc import Callable
from typing import NamedTuple

CURSOR, SPACE = 0xED, 0x7F


class Layout(NamedTuple):
    """已识别布局的菜单字段；光标缺失时不推测选中项。"""

    grid: list[list[str]]
    cell: tuple[int, int] | None
    details: list[str]
    covered: bool


def is_keyboard(tiles: list[list[int]]) -> bool:
    """识别五行命名键盘的第一排字母，允许大小写与实心光标。"""
    first = [tiles[5][column] for column in range(2, 19, 2)]
    return first in [list(range(0x80, 0x89)), list(range(0xA0, 0xA9))]


def keyboard_screen(text: str, tiles: list[list[int]]) -> str:
    """命名布局里的结束图块显示为ED；其他布局的金钱图块保持¥。"""
    if not is_keyboard(tiles):
        return text
    lines = text.split("\n")
    lines[13] = lines[13].replace("¥", "ED")
    return "\n".join(lines)


def read_layout(
    tiles: list[list[int]], characters: dict[int, str], render: Callable[[list[int]], str]
) -> Layout | None:
    """已知布局返回完整菜单；无对应布局返回None，由普通框选提取器接续。"""
    arrow = next(
        ((r, c) for r, row in enumerate(tiles) for c, t in enumerate(row) if t == CURSOR), None
    )
    if is_keyboard(tiles):
        positions = [
            (r, c, "ED" if (r, c) == (13, 18) else characters[t])
            for r in range(5, 14, 2)
            for c in range(2, 19, 2)
            if (t := tiles[r][c]) in characters and t != SPACE
        ]
        return _layout(positions, arrow, False, True, cursor_adjacent=True)
    if arrow is None:
        return None
    r, c = arrow
    if render(tiles[1]) == "TEXT SPEED":
        positions = _settings(tiles, r, render)
        if positions:
            return _layout(positions, arrow, False, True, cursor_adjacent=True)
    if "CONTENTS" in render(tiles[1]) and c == 0:
        positions = [(r, 4, render(tiles[r][4:14])) for r in range(3, 16, 2)]
        return _layout([p for p in positions if p[2]], arrow, False, True, cursor_adjacent=False)
    if c == 0 and r < 12:
        positions = _party(tiles, render)
        if positions and any(row == r - 1 for row, _, _ in positions):
            return _layout(positions, arrow, True, True, cursor_adjacent=False)
    return None


def _settings(
    tiles: list[list[int]], row: int, render: Callable[[list[int]], str]
) -> list[tuple[int, int, str]]:
    """只读实心箭头所在的设置行，标题及其他设置行不进入选项。"""
    columns = {3: (2, 8, 15), 8: (2, 11), 13: (2, 11)}.get(row, ())
    return (
        [
            (row, column, render(tiles[row][column:end]).replace("▶", "").replace("▷", "").strip())
            for column, end in zip(columns, (*columns[1:], 19), strict=True)
        ]
        if columns
        else []
    )


def _party(
    tiles: list[list[int]], render: Callable[[list[int]], str]
) -> list[tuple[int, int, str]]:
    """队伍名在等级行，下一行有HP标签；不把战斗HUD或子菜单当队伍列表。"""
    positions = []
    for row in range(0, 12, 2):
        level = next((c for c, t in enumerate(tiles[row]) if t == 0x6E), None)
        if level is None or tiles[row + 1][4] != 0x71:
            continue
        name = render(tiles[row][3:level])
        if name:
            positions.append((row, 3, name))
    return positions


def _layout(
    positions: list[tuple[int, int, str]],
    arrow: tuple[int, int] | None,
    below_name: bool,
    covered: bool,
    *, cursor_adjacent: bool,
) -> Layout:
    """按物理行列构造选项，重复名称通过坐标区分。"""
    rows: dict[int, list[tuple[int, str]]] = {}
    for row, column, label in positions:
        rows.setdefault(row, []).append((column, label))
    grid = [[label for _, label in items] for items in rows.values()]
    cell = None
    if arrow is not None:
        ar, ac = arrow
        for ri, (row, items) in enumerate(rows.items()):
            for ci, (column, _) in enumerate(items):
                if (below_name and row == ar - 1) or (
                    not below_name and row == ar and (column == ac + 1 or not cursor_adjacent)
                ):
                    cell = (ri, ci)
    return Layout(grid, cell, ["" for items in grid for _ in items], covered)
