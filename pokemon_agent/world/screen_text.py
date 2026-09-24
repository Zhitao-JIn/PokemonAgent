"""直接读屏幕文字：把 20×18 的 tile 缓冲（`wTileMap`）按《宝可梦 红》英文字表解码，
找出对话框、光标所在的选单与光标项。

**只认字表里的 tile**：其余 tile（地形、精灵、血条）一律当"非文字"，不参与拼字。
与 `ram.py` 同一条约束：地址与字表都是《红》英文版的，换版本要重来。

读法：
- 光标 = `▶`（0xED）。它所在的框由 `│` 竖边界围出（向左、向右各找最近的 `│`，
  上下沿左边界连续的 `│` 延伸）。框内每行的"选项起点"= 光标列 +1，外加
  **框内每一行有字的行都对齐**的其它起点列（战斗 2×2 菜单的第二列；背包里
  `TOWN MAP` / `POKé BALL` 这类两词名因 `CANCEL` 行不对齐而不被切开）；以 `×` 开头的数量行
  与纯数字行（`35/35`）不算选项。
- 排布 = 选项按屏幕行分组（`option_grid`），光标记为 (行, 列)——决策据此知道方向键怎么走。
- 对话 = 左下角 (12, 0) 为 `┌` 的底部框里的文字，逐行拼接。
"""

from __future__ import annotations

from collections import Counter

from .interface import Memory
from .interface.domain.screen_text import ScreenText
from .ram import SCREEN_COLS, SCREEN_ROWS, W_TILEMAP

W_IS_IN_BATTLE = 0xD057
"""战斗标志：0 = 不在战斗；1 = 野生战；2 = 训练师战。"""

CURSOR = 0xED
BOX_TOP_LEFT, BOX_HORIZONTAL, BOX_TOP_RIGHT = 0x79, 0x7A, 0x7B
BOX_VERTICAL, BOX_BOTTOM_LEFT, BOX_BOTTOM_RIGHT = 0x7C, 0x7D, 0x7E
_BORDERS = {
    BOX_TOP_LEFT,
    BOX_HORIZONTAL,
    BOX_TOP_RIGHT,
    BOX_VERTICAL,
    BOX_BOTTOM_LEFT,
    BOX_BOTTOM_RIGHT,
}
SPACE = 0x7F

CHARMAP: dict[int, str] = {
    SPACE: " ",
    0x9A: "(",
    0x9B: ")",
    0x9C: ":",
    0x9D: ";",
    0x9E: "[",
    0x9F: "]",
    0xBA: "é",
    0xBB: "'d",
    0xBC: "'l",
    0xBD: "'s",
    0xBE: "'t",
    0xBF: "'v",
    0xE0: "'",
    0xE1: "PK",
    0xE2: "MN",
    0xE3: "-",
    0xE4: "'r",
    0xE5: "'m",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xEC: "▷",
    CURSOR: "▶",
    0xEE: "▼",
    0xEF: "♂",
    0xF0: "¥",
    0xF1: "×",
    0xF2: ".",
    0xF3: "/",
    0xF4: ",",
    0xF5: "♀",
    **{0x80 + i: chr(ord("A") + i) for i in range(26)},
    **{0xA0 + i: chr(ord("a") + i) for i in range(26)},
    **{0xF6 + i: str(i) for i in range(10)},
}
"""tile id → 字符（英文版《红》字表）。不在表里的 tile 不是文字。"""


def read_tiles(mem: Memory) -> list[list[int]]:
    """屏幕 20×18 个 tile id，按行。"""
    return [
        [mem[W_TILEMAP + row * SCREEN_COLS + col] for col in range(SCREEN_COLS)]
        for row in range(SCREEN_ROWS)
    ]


def read_screen_text(mem: Memory) -> ScreenText:
    """读这一帧的对话、选项、光标与战斗标志。"""
    tiles = read_tiles(mem)
    grid, cell = _read_menu(tiles)
    return ScreenText(
        dialog_text=_read_dialog(tiles),
        options=[item for row in grid for item in row],
        cursor=grid[cell[0]][cell[1]] if cell is not None else "",
        option_grid=grid,
        cursor_cell=cell,
        in_battle=mem[W_IS_IN_BATTLE] != 0,
    )


def _text(tiles: list[int]) -> str:
    """一段 tile → 文字；非文字 tile 当空格，最后压掉多余空白。"""
    raw = "".join(CHARMAP.get(tile, " ") if tile not in _BORDERS else " " for tile in tiles)
    return " ".join(raw.replace("▼", " ").split())


def _read_dialog(tiles: list[list[int]]) -> str:
    """左下角 (12, 0) 为 `┌` 的底部框里的文字；没有这个框返回空串。"""
    top = 12
    if tiles[top][0] != BOX_TOP_LEFT:
        return ""
    right = next(
        (c for c in range(1, SCREEN_COLS) if tiles[top][c] in (BOX_TOP_RIGHT, BOX_TOP_LEFT)),
        SCREEN_COLS - 1,
    )
    lines = [_text(tiles[row][1:right]) for row in range(top + 1, SCREEN_ROWS - 1)]
    return " ".join(line for line in lines if line)


def _read_menu(tiles: list[list[int]]) -> tuple[list[list[str]], tuple[int, int] | None]:
    """光标所在框的选项（按屏幕行分组）与光标所在的 (行, 列)；没有 `▶` 时返回 `([], None)`。"""
    found = next(
        ((r, c) for r in range(SCREEN_ROWS) for c in range(SCREEN_COLS) if tiles[r][c] == CURSOR),
        None,
    )
    if found is None:
        return [], None
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
            if tiles[row][c] in CHARMAP
            and tiles[row][c] not in (SPACE, CURSOR)
            and (c == left + 1 or tiles[row][c - 1] in (SPACE, CURSOR))
        ]

    text_rows = [r for r in rows if starts(r)]
    counts = Counter(c for r in text_rows for c in starts(r))
    aligned = {c for c, n in counts.items() if n >= 2 and n == len(text_rows)}
    columns = sorted({col0 + 1} | aligned)

    # 步骤 3：逐行按起点列切出选项，过滤数量行与纯数字行；记下光标落在第几行第几列。
    grid: list[list[str]] = []
    cell: tuple[int, int] | None = None
    for r in rows:
        row_starts = [c for c in starts(r) if c in columns]
        row_items: list[str] = []
        for i, c in enumerate(row_starts):
            end = row_starts[i + 1] - 1 if i + 1 < len(row_starts) else right
            text = _text(tiles[r][c:end])
            if not text or text.startswith("×") or not any(ch.isalpha() for ch in text):
                continue
            if (r, c) == (row0, col0 + 1):
                cell = (len(grid), len(row_items))
            row_items.append(text)
        if row_items:
            grid.append(row_items)
    return grid, cell


def _vertical_run(tiles: list[list[int]], col: int, anchor: int, row: int) -> bool:
    """`row` 与 `anchor` 之间（含两端）`col` 列是否全是 `│`。"""
    lo, hi = sorted((anchor, row))
    return all(tiles[r][col] == BOX_VERTICAL for r in range(lo, hi + 1))


__all__ = ["CHARMAP", "W_IS_IN_BATTLE", "read_screen_text", "read_tiles"]
