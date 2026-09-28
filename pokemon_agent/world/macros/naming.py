"""起名键盘（`naming`）的宏：`enter_name`，外加这个场合的视图。

地址见 `docs/perceive/p0-findings.md` 第三节（开机新游戏实测）：
已输入 `wStringBuffer` 0xCF4B（0x50 收尾）、已输入长度 `wNamingScreenNameLength` 0xCEE9、
键盘光标 `wMenuCursorLocation` 0xCC30（光标所在的屏幕格，字母在它右边一格）、
大小写 `wAlphabetCase` 0xCEEB（0 = 大写）。输完按 START 提交。
"""

from __future__ import annotations

import string

from ..interface import (
    MacroParam,
    MacroReason,
    MacroSpec,
    Memory,
    NamingView,
    ScreenText,
    TaskScene,
)
from ..screen_text import CHARMAP
from .engine import Abort, MacroDef, MacroRun

W_STRING_BUFFER = 0xCF4B
W_NAME_LENGTH = 0xCEE9
W_CURSOR_LOCATION = 0xCC30
W_ALPHABET_CASE = 0xCEEB
W_TILEMAP = 0xC3A0
SCREEN_COLS = 20
NAME_END = 0x50
FIRST_KEY_ROW = 5
"""键盘第一行字母所在的屏幕行；行与行隔一行。"""
UPPER_ROWS = ("ABCDEFGHI", "JKLMNOPQR", "STUVWXYZ")
MAX_LENGTH = {"NICKNAME?": 10}
DEFAULT_MAX_LENGTH = 7
"""主角 / 对手的名字上限；宝可梦昵称是 10。"""


def naming_view(text: ScreenText, mem: Memory) -> NamingView:
    """这一帧的起名视图：屏幕标题、已输入的名字。"""
    return NamingView(target=_title(text), typed=_typed(mem))


def _title(text: ScreenText) -> str:
    return next((line.strip() for line in text.screen.splitlines() if line.strip()), "")


def _typed(mem: Memory) -> str:
    chars = []
    for i in range(DEFAULT_MAX_LENGTH + 4):
        byte = mem[W_STRING_BUFFER + i]
        if byte == NAME_END:
            break
        chars.append(CHARMAP.get(byte, "?"))
    return "".join(chars)


def _limit(run: MacroRun) -> int:
    return MAX_LENGTH.get(_title(run.screen()), DEFAULT_MAX_LENGTH)


def _check_enter(run: MacroRun, args: dict[str, str | int]) -> tuple[MacroReason, str] | None:
    name, limit = str(args["name"]), _limit(run)
    if not 1 <= len(name) <= limit:
        return MacroReason.INVALID_NAME, f"名字长度要在 1–{limit}，给的是 {len(name)}"
    if any(ch not in string.ascii_uppercase for ch in name):
        return MacroReason.INVALID_NAME, f"名字只能用大写字母，给的是 {name!r}"
    return None


def _execute_enter(run: MacroRun, args: dict[str, str | int]) -> str:
    name = str(args["name"])

    # 步骤 1：切回大写，删空已输入的字。
    if run.mem[W_ALPHABET_CASE] != 0:
        run.press("select", expect="切到大写", ok=lambda _t: run.mem[W_ALPHABET_CASE] == 0)
    for _ in range(DEFAULT_MAX_LENGTH + 4):
        if run.mem[W_NAME_LENGTH] == 0:
            break
        run.press("b", expect="删一个字")
    if run.mem[W_NAME_LENGTH] != 0:
        raise Abort(MacroReason.UNEXPECTED_SCREEN, "已输入的字删不空")

    # 步骤 2：逐字移光标、按 A。
    for i, ch in enumerate(name):
        row = next(r for r, keys in enumerate(UPPER_ROWS) if ch in keys)
        col = UPPER_ROWS[row].index(ch)
        run.move_to(lambda: _cursor(run.mem)[0], row, what=f"{ch} 所在行")
        run.move_to(lambda: _cursor(run.mem)[1], col, what=f"{ch} 所在列", increase="right")
        run.press("a", expect=f"输入 {ch}", ok=lambda _t, n=i + 1: run.mem[W_NAME_LENGTH] == n)
        if run.mem[W_NAME_LENGTH] != i + 1:
            raise Abort(
                MacroReason.UNEXPECTED_SCREEN, f"按了 {ch} 但已输入长度是 {run.mem[W_NAME_LENGTH]}"
            )
    if _typed(run.mem) != name:
        raise Abort(MacroReason.UNEXPECTED_SCREEN, f"输入的是 {_typed(run.mem)!r}，不是 {name!r}")

    # 步骤 3：START 提交，等画面离开键盘。
    run.press("start", expect="提交名字")
    run.wait_for(lambda _t: run.scene_now() is not TaskScene.NAMING, expect="离开起名键盘")
    return f"名字 {name}"


def _cursor(mem: Memory) -> tuple[int, int]:
    """键盘光标在第几行、第几列（按字母格算）。"""
    offset = (mem[W_CURSOR_LOCATION] | mem[W_CURSOR_LOCATION + 1] << 8) - W_TILEMAP
    row, col = divmod(offset, SCREEN_COLS)
    return (row - FIRST_KEY_ROW) // 2, (col - 1) // 2


NAMING_MACROS: dict[str, MacroDef] = {
    "enter_name": MacroDef(
        spec=MacroSpec(
            name="enter_name",
            params=[
                MacroParam(
                    name="name",
                    type="str",
                    description="只用大写字母；主角 / 对手最多 7 个字，昵称最多 10 个",
                )
            ],
            description="输入名字并提交（会先删掉已经输入的字）",
        ),
        scene=TaskScene.NAMING,
        check=_check_enter,
        execute=_execute_enter,
        rewind_after=False,
    ),
}


__all__ = ["NAMING_MACROS", "naming_view"]
