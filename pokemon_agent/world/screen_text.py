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

from .interface import Facts, Memory
from .interface.domain.screen_text import ScreenText
from .ram import SCREEN_COLS, SCREEN_ROWS, W_TILEMAP
from .screen_layout import keyboard_screen
from .screen_menu import read_menu

W_IS_IN_BATTLE = 0xD057


def overlay_of(text: ScreenText) -> Facts.Overlay:
    """按键控制模式：光标、数量框或完整价格列表为 CHOICE，严格对话为 DIALOG。

    DIALOG 从严：它的掩码只有 `a`，判错就按不到要按的键；判成 CHOICE / NONE 只是多给几个键。
    """
    if text.has_cursor or text.quantity_box or (text.options and any(text.option_details)):
        return Facts.Overlay.CHOICE
    if text.strict_dialog:
        return Facts.Overlay.DIALOG
    return Facts.Overlay.NONE


def layout_field(text: ScreenText) -> dict[str, str]:
    """选单排布与附注作为 `Facts` 的动态字段 `option_layout` / `option_details`（没有就不放）。

    走动态字段而不是具名字段：`ActMemory` 里的 `Facts` 快照副本按同一规则渲染动态字段，
    两份不必各加一个具名字段也不会漂。
    """
    fields: dict[str, str] = {}
    layout = text.render_layout()
    if layout:
        fields["option_layout"] = layout
    details = text.render_details()
    if details:
        fields["option_details"] = details
    return fields


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
DIALOG_TOP = 12
"""底部对话框上边所在的行。"""
DEX_TOP = 9
DEX_LEFT, DEX_RIGHT = 0x66, 0x67
DEX_CORNERS = {(DEX_TOP, 0): 0x68, (DEX_TOP, 19): 0x6A, (17, 0): 0x6C, (17, 19): 0x6E}
"""图鉴条目页说明框的边：分隔线两端、底边两角、左右竖边（图鉴专用图形，不是普通框线）。"""

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


def read_screen_text(mem: Memory) -> ScreenText:
    """读这一帧的对话、选项（含附注）、光标、叠加层判据、覆盖判定与整屏渲染。"""
    tiles = read_tiles(mem)
    menu = read_menu(tiles, CHARMAP, _text)
    in_battle = mem[W_IS_IN_BATTLE] != 0
    dialog = _read_dialog(tiles)
    has_cursor = any(CURSOR in row for row in tiles)
    quantity = _quantity_box(tiles)
    dex = _read_dex_text(tiles)
    if dex is not None:
        dialog = dex  # 图鉴说明按对话处理（用户 1007 裁决）
    dialog_box = tiles[DIALOG_TOP][0] == BOX_TOP_LEFT or dex is not None
    return ScreenText(
        dialog_text=dialog,
        has_cursor=has_cursor,
        quantity_box=quantity,
        strict_dialog=dialog_box and not has_cursor and not quantity and _only_dialog_box(tiles),
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
    text = keyboard_screen(text, tiles)
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
    top = DIALOG_TOP
    if tiles[top][0] != BOX_TOP_LEFT:
        return ""
    lines = []
    for row in range(top + 1, SCREEN_ROWS - 1):
        segment = tiles[row][1 : SCREEN_COLS - 1]
        end = next((i for i, tile in enumerate(segment) if tile in _BORDERS), len(segment))
        lines.append(_text(segment[:end]))
    return " ".join(line for line in lines if line)


def _read_dex_text(tiles: list[list[int]]) -> str | None:
    """图鉴条目页下半的说明文字；不是图鉴条目页返回 None（说明还没打出来时为空串）。"""
    framed = all(tiles[r][c] == tile for (r, c), tile in DEX_CORNERS.items()) and all(
        tiles[r][0] == DEX_LEFT and tiles[r][SCREEN_COLS - 1] == DEX_RIGHT
        for r in range(DEX_TOP + 1, SCREEN_ROWS - 1)
    )
    if not framed:
        return None
    lines = [_text(tiles[r][1 : SCREEN_COLS - 1]) for r in range(DEX_TOP + 1, SCREEN_ROWS - 1)]
    return " ".join(line for line in lines if line)


__all__ = ["CHARMAP", "W_IS_IN_BATTLE", "read_screen_text", "read_tiles", "render_screen"]
