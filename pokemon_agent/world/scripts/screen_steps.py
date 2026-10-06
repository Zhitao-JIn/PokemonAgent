"""可组合的读屏步骤：等待、文字推进与光标导航，共用 ScriptRun。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..interface import ScreenText
from .control_flow import Abort
from .execution_types import ScriptReason, ScriptStep
from .timing import (
    ADVANCE_LIMIT,
    ADVANCE_WAIT_FRAMES,
    ARROW_WINDOW,
    NAV_LIMIT,
    POLL_FRAMES,
    QUIET_PRESS_FRAMES,
    STEP_TIMEOUT_FRAMES,
)

if TYPE_CHECKING:
    from .engine import ScriptRun


def brief(text: ScreenText) -> str:
    """一步的"实际读到的"：光标项、对话、有没有数量框。"""
    parts = []
    if text.cursor:
        parts.append(f"▶{text.cursor}")
    if text.quantity_box:
        parts.append("数量框")
    if text.dialog_text:
        parts.append(text.dialog_text[:40])
    return "；".join(parts) or "（屏上没有文字）"


def wait_for(
    self: ScriptRun,
    ok: Callable[[ScreenText], bool],
    *,
    expect: str,
    advance: Callable[[ScreenText], bool] | None = None,
) -> ScreenText:
    """等某个画面：没到、且 `advance` 说可以时替它按 A 推进文字（最多 `ADVANCE_LIMIT` 次）。

    等不到抛 `Abort`。

    advance：这一帧按 A 安全吗。缺省 = 屏上既没有光标 `▶` 也没有数量框——
        有的话按 A 会替 JEV 选掉一项。数量已确认、只剩报价文字时，调用方放宽成"没有光标"。
    """
    safe = advance or (lambda t: not t.has_cursor and not t.quantity_box)
    frames = self.settle()
    text = self.console.read()
    self.record_step(
        ScriptStep(key="", frames=frames, expect=expect, actual=brief(text), ok=ok(text))
    )
    for _ in range(ADVANCE_LIMIT):
        if ok(text) or not safe(text):
            break
        text = self.press_screen("a", expect=expect, ok=ok)
    if ok(text):
        return text
    raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"没等到：{expect}；屏上是：{brief(text)}")


def idle_until(self: ScriptRun, ok: Callable[[ScreenText], bool], *, expect: str) -> ScreenText:
    """不按键干等某个画面，最多 `STEP_TIMEOUT_FRAMES` 帧（存档时画面静止、游戏在忙）。"""
    waited = 0
    text = self.console.read()
    while not ok(text) and waited < STEP_TIMEOUT_FRAMES:
        self.console.tick(POLL_FRAMES)
        waited += POLL_FRAMES
        text = self.console.read()
    self.record_step(
        ScriptStep(key="", frames=waited, expect=expect, actual=brief(text), ok=ok(text))
    )
    if not ok(text):
        raise Abort(ScriptReason.STEP_TIMEOUT, f"{STEP_TIMEOUT_FRAMES} 帧内没等到：{expect}")
    self.settle()
    return text


def advance(self: ScriptRun, stop: Callable[[ScreenText], str]) -> str:
    """自动推进文字：`stop` 给出非空的停止原因即停；只在看到 `▼`（游戏在等按键）时按 A。

    文字自己在走时不按——按早了会落在紧接着出现的选单上，替 JEV 选掉一项；
    画面静止满 `QUIET_PRESS_FRAMES` 帧也没有 `▼` 时才按。
    按满 `ADVANCE_LIMIT` 次或空等满 `ADVANCE_WAIT_FRAMES` 帧也停，返回说明。
    """
    self.settle()
    presses = waited = quiet = 0
    last = ""
    while presses < ADVANCE_LIMIT and waited < ADVANCE_WAIT_FRAMES:
        text = self.console.read()
        reason = stop(text)
        if reason:
            self.record_step(
                ScriptStep(key="", frames=waited, expect="推进文字", actual=brief(text))
            )
            return reason
        arrow = self._saw_arrow()
        text = self.console.read()
        reason = stop(text)
        if reason:
            continue
        now = text.screen.replace("▼", " ")
        quiet = quiet + ARROW_WINDOW if now == last else 0
        last = now
        if arrow or quiet >= QUIET_PRESS_FRAMES:
            self.press_screen("a", expect="推进文字")
            presses, quiet = presses + 1, 0
        else:
            waited += ARROW_WINDOW
    return f"推进 {presses} 次、空等 {waited} 帧后仍未停"


def saw_arrow(self: ScriptRun) -> bool:
    """再看 `ARROW_WINDOW` 帧，期间屏上出现过 `▼` 吗。"""
    seen = False
    for _ in range(ARROW_WINDOW // POLL_FRAMES):
        self.console.tick(POLL_FRAMES)
        seen = seen or "▼" in self.console.read().screen
    return seen


def move_to(
    self: ScriptRun, read: Callable[[], int], target: int, *, what: str, increase: str = "down"
) -> None:
    """按键把 `read()` 读出的值挪到 `target`；挪不到抛 `Abort`。

    increase：让值变大的键——列表光标是 `down`，数量框是 `up`。
    """
    decrease = {"down": "up", "up": "down", "right": "left", "left": "right"}[increase]
    for _ in range(NAV_LIMIT):
        now = read()
        if now == target:
            return
        self.press_screen(increase if now < target else decrease, expect=f"{what} → {target}")
    if read() != target:
        raise Abort(ScriptReason.UNEXPECTED_SCREEN, f"{what} 停在 {read()}，挪不到 {target}")
