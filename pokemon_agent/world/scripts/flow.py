"""流程类脚本（§7.4）：advance_dialog / wait_until_scene。

这两类都发生在**没有常驻光标**的窗口里（纯对话推进、过场等待），所以可以放心
走 `ScriptRun.press`（它的三钩子只会在战斗 / 选项 / 换图时停——对话帧没有光标，
不会误触 `choice_presented`）。

**raw 推进 vs 钩子**：`advance_dialog` 走钩子路径——真遇到选项框照常冻结
（`choice_presented`），绝不替调用方做分叉；`wait_until_scene` 不按键只 tick，
逐帧判场合，超时 `timeout`。
"""

from __future__ import annotations

from typing import Any

from .engine import Halt, ScriptResult, ScriptRun, WorldConsole, _dialog_texts
from .movement import _run
from .takeover.engine import POLL_FRAMES

_WALK = "walk"


def advance_dialog(console: WorldConsole, max_presses: int = 30) -> ScriptResult:
    """推进当前对话框到底：反复按 a 直到画面回野外（对话关闭）或出选项 / 进战斗。

    - 三框对话收完回野外 → `ok`；
    - 预算内推不完 → `still_talking`；
    - 中途出选项框 → `choice_presented`（冻结，绝不代选）；
    - 进战斗 → `battle_started`。
    """
    run = _run(console, budget=max_presses)
    presses = 0
    try:
        while presses < max_presses:
            if run.budget <= 0:
                return run.finish(
                    ok=False, code="still_talking", extra=_adv_extra(run, console, presses)
                )
            run.budget -= 1
            presses += 1
            run.press("a")
            text = console.read()
            # 对话结束：场合回野外且无对话文字、无光标（不该有光标，但兜底）
            if console.scene() == _WALK or (not text.dialog_text and not text.has_cursor):
                return run.finish(ok=True, code="ok", extra=_adv_extra(run, console, presses))
        return run.finish(ok=False, code="still_talking", extra=_adv_extra(run, console, presses))
    except Halt as halt:
        extra: dict[str, Any] = _adv_extra(run, console, presses)
        extra.update(halt.extra)
        if halt.code == "choice_presented":
            # 对话里嵌了选项：冻结，已收文本照带
            return run.finish(ok=False, code="choice_presented", extra=extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=extra)


def _adv_extra(run: ScriptRun, console: WorldConsole, presses: int) -> dict[str, Any]:
    return {
        "presses": presses,
        "dialog": _dialog_texts(run),
        "final_screen_text": console.read().screen,
    }


def wait_until_scene(console: WorldConsole, scene: str, timeout_s: float = 10.0) -> ScriptResult:
    """干等画面变成 `scene`：不按键、只 tick，逐帧判场合；超时 → `timeout`。

    用于过场 / 淡入 / 战斗结束这类"等它自己变"的窗口（退出地图后的新图淡入、
    进化动画、回血白闪等）。约 60fps 估算帧预算；预算内任一次判等即 `ok`。
    """
    frames_budget = max(int(timeout_s * 60), POLL_FRAMES)
    run = ScriptRun(
        console,
        budget=frames_budget,
        start_map_id=console.map_id(),
        start_pos=console.pos(),
    )
    waited = 0
    while waited < frames_budget:
        if console.scene() == scene:
            return run.finish(ok=True, code="ok", extra={"waited_frames": waited})
        console.tick(POLL_FRAMES)
        waited += POLL_FRAMES
    if console.scene() == scene:
        return run.finish(ok=True, code="ok", extra={"waited_frames": waited})
    return run.finish(
        ok=False,
        code="timeout",
        extra={"waited_frames": waited, "scene": console.scene()},
    )


__all__ = ["advance_dialog", "wait_until_scene"]
