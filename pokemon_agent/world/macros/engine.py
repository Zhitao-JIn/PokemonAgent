"""宏执行器的通用骨架：回初态 → 校验 → 逐步执行（按键后等画面稳定、核期望）→ 收尾。

每个场合的宏只写"前提校验 + 步骤 + 收尾"（`shop.py` 等），骨架与按键细节都在这里。
回初态、等稳定、超时这些是 world 私有物理量，不进全局 config。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..interface import (
    TAKEOVER_SCENES,
    MacroOutcome,
    MacroReason,
    MacroSpec,
    MacroStatus,
    MacroStep,
    Memory,
    ScreenText,
    TaskScene,
)
from ..scene import at_start, classify_scene

POLL_FRAMES = 4
"""等画面稳定时每隔几帧看一次屏幕缓冲。"""
STABLE_POLLS = 6
"""连续几次一模一样才算稳定（游戏处理按键时会擦掉 `▶` 重画，对话会逐字打出）。"""
STEP_TIMEOUT_FRAMES = 900
"""一步最多等多少帧画面稳定（约 15 秒）。"""
REWIND_LIMIT = 10
"""回初态最多按几次 B。"""
ADVANCE_LIMIT = 30
"""等某个画面出现、或自动推进战斗文字时，最多替它按几次 A。"""
ARROW_WINDOW = 48
"""看一眼 `▼` 要看多少帧：`▼` 约 36 帧亮、34 帧灭（战斗文字实测），窗口要盖住一整段灭。"""
ADVANCE_WAIT_FRAMES = 3600
"""自动推进时，没有 `▼`（文字自己在走）最多等多少帧。"""
QUIET_PRESS_FRAMES = 300
"""画面一动不动、也没有 `▼` 这么多帧，就当游戏在等按键（战斗里对队员用药后的那句话就这样等）。
文字自己在走时最长的静止约 200 帧（扣血动画），比它长。"""
NAV_LIMIT = 120
"""移光标 / 调数量最多按几次。"""


class Console(Protocol):
    """宏看得到的那一小块模拟器：按键、推进、读内存与屏幕、ROM。"""

    memory: Memory
    rom: bytes

    def press(self, key: str) -> None:
        """按下并按住一小会儿（松开在之后的帧里发生）。"""
        ...

    def tick(self, frames: int) -> None:
        """推进 N 帧。"""
        ...

    def read(self) -> ScreenText:
        """解码这一帧的屏幕缓冲。"""
        ...


class Abort(Exception):  # noqa: N818 —— 宏内部的控制流信号，不出本包
    """执行中途没出现期望的变化：骨架接住它，按 B 回初态，返回 `aborted`。"""

    def __init__(self, code: MacroReason, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason


Check = Callable[["MacroRun", dict[str, str | int]], tuple[MacroReason, str] | None]
Execute = Callable[["MacroRun", dict[str, str | int]], str]


@dataclass(frozen=True)
class MacroDef:
    """一个宏：签名、所属场合、前提校验（不合法返回原因码与原因）、执行（返回状态摘要）。"""

    spec: MacroSpec
    scene: TaskScene
    check: Check
    execute: Execute
    rewind_after: bool = True
    """执行完是否按 B 回到初态（离开场合的宏为 False）。"""


class MacroRun:
    """一次宏调用的现场：按键、等稳定、记逐步明细。"""

    def __init__(self, console: Console, scene: TaskScene) -> None:
        self.console, self.scene = console, scene
        self.steps: list[MacroStep] = []

    @property
    def mem(self) -> Memory:
        return self.console.memory

    def screen(self) -> ScreenText:
        """这一帧的屏幕（不推进）。"""
        return self.console.read()

    def scene_now(self) -> TaskScene:
        return classify_scene(self.console.read(), self.console.memory)

    def settle(self) -> int:
        """推进到屏幕缓冲连续 `STABLE_POLLS` 次不变（`▼` 闪烁不算变）。

        返回等了多少帧；超时抛 `Abort`。
        """
        waited, same, last = 0, 0, None
        while waited < STEP_TIMEOUT_FRAMES:
            self.console.tick(POLL_FRAMES)
            waited += POLL_FRAMES
            now = self.console.read().screen.replace("▼", " ")
            same = same + 1 if now == last else 0
            last = now
            if same >= STABLE_POLLS:
                return waited
        raise Abort(MacroReason.STEP_TIMEOUT, f"画面 {STEP_TIMEOUT_FRAMES} 帧内没有稳定下来")

    def press(
        self, key: str, *, expect: str = "", ok: Callable[[ScreenText], bool] | None = None
    ) -> ScreenText:
        """按一个键、等稳定、记一步；给了 `ok` 就核期望（不抛，由调用方决定怎么办）。"""
        self.console.press(key)
        frames = self.settle()
        text = self.console.read()
        passed = ok(text) if ok is not None else True
        self.steps.append(
            MacroStep(key=key, frames=frames, expect=expect, actual=_brief(text), ok=passed)
        )
        return text

    def wait_for(
        self,
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
        self.steps.append(
            MacroStep(key="", frames=frames, expect=expect, actual=_brief(text), ok=ok(text))
        )
        for _ in range(ADVANCE_LIMIT):
            if ok(text) or not safe(text):
                break
            text = self.press("a", expect=expect, ok=ok)
        if ok(text):
            return text
        raise Abort(MacroReason.UNEXPECTED_SCREEN, f"没等到：{expect}；屏上是：{_brief(text)}")

    def idle_until(self, ok: Callable[[ScreenText], bool], *, expect: str) -> ScreenText:
        """不按键干等某个画面，最多 `STEP_TIMEOUT_FRAMES` 帧（存档时画面静止、游戏在忙）。"""
        waited = 0
        text = self.console.read()
        while not ok(text) and waited < STEP_TIMEOUT_FRAMES:
            self.console.tick(POLL_FRAMES)
            waited += POLL_FRAMES
            text = self.console.read()
        self.steps.append(
            MacroStep(key="", frames=waited, expect=expect, actual=_brief(text), ok=ok(text))
        )
        if not ok(text):
            raise Abort(MacroReason.STEP_TIMEOUT, f"{STEP_TIMEOUT_FRAMES} 帧内没等到：{expect}")
        self.settle()
        return text

    def advance(self, stop: Callable[[ScreenText], str]) -> str:
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
                self.steps.append(
                    MacroStep(key="", frames=waited, expect="推进文字", actual=_brief(text))
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
                self.press("a", expect="推进文字")
                presses, quiet = presses + 1, 0
            else:
                waited += ARROW_WINDOW
        return f"推进 {presses} 次、空等 {waited} 帧后仍未停"

    def _saw_arrow(self) -> bool:
        """再看 `ARROW_WINDOW` 帧，期间屏上出现过 `▼` 吗。"""
        seen = False
        for _ in range(ARROW_WINDOW // POLL_FRAMES):
            self.console.tick(POLL_FRAMES)
            seen = seen or "▼" in self.console.read().screen
        return seen

    def move_to(
        self, read: Callable[[], int], target: int, *, what: str, increase: str = "down"
    ) -> None:
        """按键把 `read()` 读出的值挪到 `target`；挪不到抛 `Abort`。

        increase：让值变大的键——列表光标是 `down`，数量框是 `up`。
        """
        decrease = {"down": "up", "up": "down", "right": "left", "left": "right"}[increase]
        for _ in range(NAV_LIMIT):
            now = read()
            if now == target:
                return
            self.press(increase if now < target else decrease, expect=f"{what} → {target}")
        if read() != target:
            raise Abort(MacroReason.UNEXPECTED_SCREEN, f"{what} 停在 {read()}，挪不到 {target}")

    def rewind(self) -> MacroStatus | None:
        """回初态：已在初态返回 None；场合变了返回 `LEFT_SCENE`。

        按满 `REWIND_LIMIT` 次 B 还没到返回 `ABORTED`。
        """
        for _ in range(REWIND_LIMIT + 1):
            self.settle()
            text = self.console.read()
            scene = classify_scene(text, self.console.memory)
            if scene is not self.scene:
                return MacroStatus.LEFT_SCENE
            if at_start(text, scene):
                return None
            self.press("b", expect="回初态")
        return MacroStatus.ABORTED


def run_macro(
    console: Console,
    macros: dict[TaskScene, dict[str, MacroDef]],
    name: str,
    args: dict[str, str | int],
) -> MacroOutcome:
    """执行一个宏，返回结果。不抛异常：未知宏、参数不合法、执行中途走偏都是返回值。

    步骤 1：认场合、找宏、核参数类型。
    步骤 2：回初态。
    步骤 3：按此刻内存校验前提。
    步骤 4：执行；走偏就回初态、返回 `aborted`。
    步骤 5：收尾回初态（离开场合的宏不回）。
    """
    # 步骤 1。
    text = console.read()
    scene = classify_scene(text, console.memory)
    macro = macros.get(scene, {}).get(name)
    outcome = _Outcome(scene, name, args)
    if scene not in TAKEOVER_SCENES or macro is None:
        return outcome.make(
            MacroStatus.REJECTED, [], MacroReason.UNKNOWN_MACRO, f"{scene.value} 场合没有宏 {name}"
        )
    bad = _bad_args(macro.spec, args)
    if bad:
        return outcome.make(MacroStatus.REJECTED, [], MacroReason.BAD_ARGS, bad)
    args = _with_defaults(macro.spec, args)

    # 步骤 2。
    run = MacroRun(console, scene)
    try:
        rewound = run.rewind()
    except Abort as exc:
        return outcome.make(MacroStatus.ABORTED, run.steps, exc.code, exc.reason)
    if rewound is MacroStatus.LEFT_SCENE:
        return outcome.make(MacroStatus.LEFT_SCENE, run.steps, None, "回初态时已离开本场合")
    if rewound is MacroStatus.ABORTED:
        return outcome.make(
            MacroStatus.ABORTED, run.steps, MacroReason.REWIND_LIMIT, "按 B 回不到初态"
        )

    # 步骤 3。
    rejected = macro.check(run, args)
    if rejected is not None:
        return outcome.make(MacroStatus.REJECTED, run.steps, rejected[0], rejected[1])

    # 步骤 4。
    try:
        summary = macro.execute(run, args)
    except Abort as exc:
        with contextlib.suppress(Abort):
            run.rewind()
        return outcome.make(MacroStatus.ABORTED, run.steps, exc.code, exc.reason)

    # 步骤 5。
    if macro.rewind_after:
        with contextlib.suppress(Abort):
            run.rewind()
    return outcome.make(MacroStatus.DONE, run.steps, None, "", summary)


@dataclass(frozen=True)
class _Outcome:
    scene: TaskScene
    macro: str
    args: dict[str, str | int]

    def make(
        self,
        status: MacroStatus,
        steps: list[MacroStep],
        code: MacroReason | None,
        reason: str,
        summary: str = "",
    ) -> MacroOutcome:
        return MacroOutcome(
            scene=self.scene,
            macro=self.macro,
            args=self.args,
            status=status,
            reason_code=code,
            reason=reason,
            summary=summary,
            steps=list(steps),
        )


def _bad_args(spec: MacroSpec, args: dict[str, str | int]) -> str:
    """参数与签名对不上时返回一句原因；对得上返回空串。"""
    known = {p.name for p in spec.params}
    extra = sorted(set(args) - known)
    if extra:
        return f"{spec.name} 没有参数 {extra}"
    for p in spec.params:
        if p.name not in args:
            if p.default is None:
                return f"{spec.name} 缺参数 {p.name}"
            continue
        value = args[p.name]
        if p.type == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            return f"{p.name} 要整数，给的是 {value!r}"
        if p.type == "str" and not isinstance(value, str):
            return f"{p.name} 要字符串，给的是 {value!r}"
    return ""


def _with_defaults(spec: MacroSpec, args: dict[str, str | int]) -> dict[str, str | int]:
    filled = dict(args)
    for p in spec.params:
        if p.name not in filled and p.default is not None:
            filled[p.name] = p.default
    return filled


def _brief(text: ScreenText) -> str:
    """一步的"实际读到的"：光标项、对话、有没有数量框。"""
    parts = []
    if text.cursor:
        parts.append(f"▶{text.cursor}")
    if text.quantity_box:
        parts.append("数量框")
    if text.dialog_text:
        parts.append(text.dialog_text[:40])
    return "；".join(parts) or "（屏上没有文字）"


__all__ = ["Abort", "Check", "Console", "Execute", "MacroDef", "MacroRun", "run_macro"]
