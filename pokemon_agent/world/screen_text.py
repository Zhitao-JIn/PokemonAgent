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
- 整屏渲染（`render_screen`）= 20×18 原样逐行渲成文字，交给模型与切好的字段互相校验：
  边框画成 `┌─┐│└┘`，等级 `:L`、血条 `HP:[██████]` 按图块渲染，其余非文字图块画 `·`。
- 叠加层判据：屏幕上有 `▶` 或数量框（`×` 紧跟两位数字）→ 有选单；
  严格对话 = 底部对话框有字、没有 `▶`、没有数量框、对话框外没有别的框。
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

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

LEVEL, HP_LABEL, BAR_LEFT = 0x6E, 0x71, 0x62
BAR_EMPTY, BAR_FULL = 0x63, 0x6B
BAR_RIGHT = frozenset({0x6C, 0x6D})
QUANTITY_DIGITS = 2
_BAR = {BAR_EMPTY + i: " ▏▎▍▌▋▊▉█"[i] for i in range(BAR_FULL - BAR_EMPTY + 1)}
_LINES = {
    BOX_TOP_LEFT: "┌",
    BOX_HORIZONTAL: "─",
    BOX_TOP_RIGHT: "┐",
    BOX_VERTICAL: "│",
    BOX_BOTTOM_LEFT: "└",
    BOX_BOTTOM_RIGHT: "┘",
    0x6F: "└",
    0x76: "─",
    0x77: "┘",
    0x78: "│",
}
"""只在渲染整屏时用的图块：边框（含战斗 HUD 的框线 0x6F / 0x76–0x78）、等级、血条。
0x73 / 0x74 在菜单字体里是 `ID` / `No.`，在战斗 HUD 里是框线，只在战斗外按字渲染。"""


def read_tiles(mem: Memory) -> list[list[int]]:
    """屏幕 20×18 个 tile id，按行。"""
    return [
        [mem[W_TILEMAP + row * SCREEN_COLS + col] for col in range(SCREEN_COLS)]
        for row in range(SCREEN_ROWS)
    ]


_NOTE_PREFIXES: tuple[str, ...] = ("×", "¥")
"""选单里挂在上一项下面的附注行：数量（`× 4`）与价格（`¥200`）。"""


class _Menu(NamedTuple):
    """光标所在框的解码结果。"""

    grid: list[list[str]]
    cell: tuple[int, int] | None
    details: list[str]
    covered: bool


def read_screen_text(mem: Memory) -> ScreenText:
    """读这一帧的对话、选项（含附注）、光标、叠加层判据、覆盖判定与整屏渲染。"""
    tiles = read_tiles(mem)
    menu = _read_menu(tiles)
    in_battle = mem[W_IS_IN_BATTLE] != 0
    dialog = _read_dialog(tiles)
    has_cursor = any(CURSOR in row for row in tiles)
    quantity = _quantity_box(tiles)
    return ScreenText(
        dialog_text=dialog,
        has_cursor=has_cursor,
        quantity_box=quantity,
        strict_dialog=bool(dialog) and not has_cursor and not quantity and _only_dialog_box(tiles),
        screen=render_screen(tiles, in_battle=in_battle),
        options=[item for row in menu.grid for item in row],
        cursor=menu.grid[menu.cell[0]][menu.cell[1]] if menu.cell is not None else "",
        option_grid=menu.grid,
        cursor_cell=menu.cell,
        option_details=menu.details,
        covered=menu.covered,
        in_battle=in_battle,
    )


def render_screen(tiles: list[list[int]], *, in_battle: bool) -> str:
    """整屏逐行渲成文字；行尾空白去掉，行数不变（空行留着，保住上下位置关系）。

    一个图块渲成一个字符，只有 `:L` 与 `HP:` 两个图块各占两三个字符，所在行后面的列会右移。
    整屏既没有字也没有边框（走路、过场）时返回空串：18 行 `·` 不带任何信息，只占 prompt。
    """
    text = "\n".join(_render_row(row, in_battle).rstrip() for row in tiles)
    return text if text.strip("·\n ") else ""


def _render_row(row: list[int], in_battle: bool) -> str:
    """一行图块渲成文字。

    0x62–0x74 这批图块的样子随当时载入的图形变：在战斗 / 队伍列表 / 能力页里是血条、`:L`、
    `ID` / `No.`，在城镇地图、图鉴页里是别的图形（0926 实采：城镇地图渲出一串 `▍▍▌]`）。
    所以它们只在**成形**时按 HUD 渲：血条要是完整的 `HP:[…]`，`:L` 后面要跟数字，
    `ID` 后面要跟 `No.`，`No.` 后面要跟 `.` 或数字；不成形的一律 `·`。
    """
    hud = _hud_positions(row, in_battle)
    return "".join(
        _glyph(t) if t in CHARMAP or t in _LINES or i in hud else "·" for i, t in enumerate(row)
    )


def _hud_positions(row: list[int], in_battle: bool) -> set[int]:
    """这一行里成形的 HUD 图块的位置。"""
    digits = set(range(0xF6, 0x100))
    after = [*row[1:], SPACE]
    ok: set[int] = set()
    for i, (tile, nxt) in enumerate(zip(row, after, strict=True)):
        if tile == HP_LABEL and nxt == BAR_LEFT:
            end = i + 2
            while end < len(row) and row[end] in _BAR:
                end += 1
            if end > i + 2 and end < len(row) and row[end] in BAR_RIGHT:
                ok.update(range(i, end + 1))
        level = tile == LEVEL and nxt in digits
        id_no = not in_battle and (
            (tile == 0x73 and nxt == 0x74) or (tile == 0x74 and (nxt in digits or nxt == 0xF2))
        )
        if level or id_no:
            ok.add(i)
    return ok


def _glyph(tile: int) -> str:
    """一个图块在整屏渲染里的样子（调用方已判过它该不该按 HUD 渲）。"""
    if tile in CHARMAP:
        return CHARMAP[tile]
    if tile in _LINES:
        return _LINES[tile]
    if tile in _BAR:
        return _BAR[tile]
    if tile in BAR_RIGHT:
        return "]"
    return {LEVEL: ":L", HP_LABEL: "HP:", BAR_LEFT: "[", 0x73: "ID", 0x74: "No."}.get(tile, "·")


def _quantity_box(tiles: list[list[int]]) -> bool:
    """屏幕上有数量框：框的左边线后紧跟 `×` 与两位数字（`│×01`）。

    背包列表里的数量是 `× 3` / `×12`，前面是空白而不是框线，不算。
    """
    digits = {0xF6 + i for i in range(10)}
    return any(
        row[c - 1] == BOX_VERTICAL
        and row[c] == 0xF1
        and all(row[c + 1 + k] in digits for k in range(QUANTITY_DIGITS))
        for row in tiles
        for c in range(1, SCREEN_COLS - QUANTITY_DIGITS)
    )


def _only_dialog_box(tiles: list[list[int]]) -> bool:
    """屏幕上唯一的框是底部对话框：对话框自己的边之外，任何地方都没有框线图块。"""
    top, bottom, right = 12, SCREEN_ROWS - 1, SCREEN_COLS - 1
    for r, row in enumerate(tiles):
        for c, tile in enumerate(row):
            if tile not in _BORDERS:
                continue
            on_dialog_edge = top <= r <= bottom and (r in (top, bottom) or c in (0, right))
            if not on_dialog_edge:
                return False
    return True


def _text(tiles: list[int]) -> str:
    """一段 tile → 文字；非文字 tile 当空格，最后压掉多余空白。"""
    raw = "".join(CHARMAP.get(tile, " ") if tile not in _BORDERS else " " for tile in tiles)
    return " ".join(raw.replace("▼", " ").split())


def _read_dialog(tiles: list[list[int]]) -> str:
    """左下角 (12, 0) 为 `┌` 的底部框里的文字；没有这个框返回空串。

    每行读到第一个边框图块为止：压在对话框上的小菜单（队伍子菜单等）不混进对话。
    """
    top = 12
    if tiles[top][0] != BOX_TOP_LEFT:
        return ""
    lines = []
    for row in range(top + 1, SCREEN_ROWS - 1):
        segment = tiles[row][1 : SCREEN_COLS - 1]
        end = next((i for i, tile in enumerate(segment) if tile in _BORDERS), len(segment))
        lines.append(_text(segment[:end]))
    return " ".join(line for line in lines if line)


def _read_menu(tiles: list[list[int]]) -> _Menu:
    """光标所在框的选项（按屏幕行分组）、光标所在的 (行, 列)、每项附注与覆盖判定。

    没有 `▶` 时返回空选单且视为已覆盖。覆盖判定见 `_covered`。
    """
    found = next(
        ((r, c) for r in range(SCREEN_ROWS) for c in range(SCREEN_COLS) if tiles[r][c] == CURSOR),
        None,
    )
    if found is None:
        return _Menu([], None, [], True)
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
    details: list[str] = []
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
            details.extend("" for _ in row_items)
            continue

        # 步骤 4：没切出选项的行若是附注（数量 / 价格），挂到上一项。
        note = _box_line(tiles, r, left, right)
        if details and note.startswith(_NOTE_PREFIXES):
            details[-1] = f"{details[-1]} {note}".strip()

    options = [item for row in grid for item in row]
    covered = left >= 0 and bool(options) and _covered(tiles, rows, left, right, options)
    return _Menu(grid, cell, details, covered)


def _box_line(tiles: list[list[int]], row: int, left: int, right: int) -> str:
    """光标所在框里一行的文字，去掉光标记号。"""
    return _text(tiles[row][left + 1 : right]).replace("▶", " ").replace("▷", " ").strip()


def _covered(
    tiles: list[list[int]], rows: list[int], left: int, right: int, options: list[str]
) -> bool:
    """框里每一行的文字都已分进某个选项才算解码覆盖了这一帧。

    不含字母的行不算（等级 `:L10` 只剩数字、空招式位 `-`、`35/35`），数量 / 价格附注行不算。

    调用方已保证框有左边界且切出了选项；未覆盖的帧，文字字段交给视觉（看档路径）或留空（task 层）。
    """
    for r in rows:
        line = _box_line(tiles, r, left, right)
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


__all__ = ["CHARMAP", "W_IS_IN_BATTLE", "read_screen_text", "read_tiles", "render_screen"]
