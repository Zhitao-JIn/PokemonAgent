"""屏幕菜单的定位与提取；字表和文字渲染器由调用方提供。"""

from collections import Counter
from collections.abc import Callable
from typing import NamedTuple

from .priced_menu import read_priced_menu
from .ram import SCREEN_COLS, SCREEN_ROWS
from .screen_layout import read_layout

CURSOR, SPACE, BOX_VERTICAL = 0xED, 0x7F, 0x7C
_NOTE_PREFIXES = ("×", "¥")


class Menu(NamedTuple):
    """光标所在框或完整价格列表的解析结果。"""

    grid: list[list[str]]
    cell: tuple[int, int] | None
    details: list[str]
    covered: bool


def read_menu(
    tiles: list[list[int]], characters: dict[int, str], render_text: Callable[[list[int]], str],
    *, in_battle: bool = False,
) -> Menu:
    """光标所在框的选项（按屏幕行分组）、光标所在的 (行, 列)、每项附注与覆盖判定。

    没有 `▶` 时仍读取完整商品价格框，但不推测光标。覆盖判定见 `_covered`。
    """
    layout = read_layout(tiles, characters, render_text)
    if layout is not None:
        return Menu(*layout)
    found = next(
        ((r, c) for r in range(SCREEN_ROWS) for c in range(SCREEN_COLS) if tiles[r][c] == CURSOR),
        None,
    )
    if found is None:
        priced = read_priced_menu(tiles, render_text)
        return Menu([[name] for name, _ in priced], None, [price for _, price in priced], True)
    row0, col0 = found

    # 步骤 1：围出光标所在的框（左右最近的 │，上下沿左边界延伸）。
    left = next((c for c in range(col0 - 1, -1, -1) if tiles[row0][c] == BOX_VERTICAL), -1)
    right = next(
        (c for c in range(col0 + 1, SCREEN_COLS) if tiles[row0][c] == BOX_VERTICAL), SCREEN_COLS
    )
    rows = [row0]
    if left >= 0:
        rows = [r for r in range(SCREEN_ROWS) if _vertical_run(tiles, left, row0, r)]

    # 步骤 2：找选项起点列——光标列 +1，加上至少两行对齐的其它起点。
    def starts(row: int) -> list[int]:
        return [
            c
            for c in range(left + 1, right)
            if tiles[row][c] in characters
            and tiles[row][c] not in (SPACE, CURSOR)
            and (c == left + 1 or tiles[row][c - 1] in (SPACE, CURSOR))
        ]

    text_rows = [r for r in rows if starts(r)]
    counts = Counter(c for r in text_rows for c in starts(r))
    aligned = {c for c, n in counts.items() if n >= 2 and n == len(text_rows)}
    columns = sorted({col0 + 1} | aligned)

    empty_moves = in_battle and left == 4 and all(
        tiles[row][4] == tiles[row][19] == BOX_VERTICAL for row in range(13, 17)
    )
    return _extract_menu(
        tiles, rows, left, right, row0, col0, columns, starts, render_text, empty_moves
    )


def _extract_menu(
    tiles: list[list[int]],
    rows: list[int],
    left: int,
    right: int,
    row0: int,
    col0: int,
    columns: list[int],
    starts: Callable[[int], list[int]],
    render_text: Callable[[list[int]], str],
    empty_moves: bool,
) -> Menu:
    """从定位完成的框中提取排布、光标和价格附注。"""
    # 步骤 3：逐行切出选项，滤掉数量、纯数字与战斗招式空位。
    grid: list[list[str]] = []
    details: list[str] = []
    cell: tuple[int, int] | None = None
    for r in rows:
        row_starts = [c for c in starts(r) if c in columns]
        row_items: list[str] = []
        for i, c in enumerate(row_starts):
            end = row_starts[i + 1] - 1 if i + 1 < len(row_starts) else right
            text = render_text(tiles[r][c:end])
            if empty_moves and text == "-":
                continue
            if not text or text.startswith("×") or not _is_item(text):
                continue
            if (r, c) == (row0, col0 + 1):
                cell = (len(grid), len(row_items))
            row_items.append(text)
        if row_items:
            grid.append(row_items)
            details.extend("" for _ in row_items)
            continue

        # 步骤 4：没切出选项的行若是附注（数量 / 价格），挂到上一项。
        note = _box_line(tiles, r, left, right, render_text)
        if details and note.startswith(_NOTE_PREFIXES):
            details[-1] = f"{details[-1]} {note}".strip()

    options = [item for row in grid for item in row]
    covered = (
        left >= 0 and bool(options) and _covered(tiles, rows, left, right, options, render_text)
    )
    return Menu(grid, cell, details, covered)


def _is_item(text: str) -> bool:
    """切出的一段算不算选项：含字母，或整段是 `-`（空招式位 `-`、图鉴未见条目 `----------`）。"""
    return any(ch.isalpha() for ch in text) or set(text) == {"-"}


def _box_line(
    tiles: list[list[int]], row: int, left: int, right: int, render_text: Callable[[list[int]], str]
) -> str:
    """光标所在框里一行的文字，去掉光标记号。"""
    return render_text(tiles[row][left + 1 : right]).replace("▶", " ").replace("▷", " ").strip()


def _covered(
    tiles: list[list[int]],
    rows: list[int],
    left: int,
    right: int,
    options: list[str],
    render_text: Callable[[list[int]], str],
) -> bool:
    """框里每一行的文字都已分进某个选项才算解码覆盖了这一帧。

    不含字母的行不算（等级 `:L10` 只剩数字、空招式位 `-`、`35/35`），数量 / 价格附注行不算。

    调用方已保证框有左边界且切出了选项；未覆盖的帧，文字字段交给视觉（看档路径）或留空（task 层）。
    """
    for r in rows:
        line = _box_line(tiles, r, left, right, render_text)
        if not any(ch.isalpha() for ch in line) or line.startswith(_NOTE_PREFIXES):
            continue
        rest = line
        for option in sorted(set(options), key=len, reverse=True):
            rest = rest.replace(option, " ")
        if rest.strip():
            return False
    return True


def _vertical_run(tiles: list[list[int]], col: int, anchor: int, row: int) -> bool:
    """`row` 与 `anchor` 之间（含两端）`col` 列是否全是 `│`。"""
    lo, hi = sorted((anchor, row))
    return all(tiles[r][col] == BOX_VERTICAL for r in range(lo, hi + 1))
