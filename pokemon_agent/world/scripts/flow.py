"""对话推进与场合等待。

advance_dialog 显式选择地图操作的战斗、选项与换图中断；wait_until_scene 只推进帧，
以指定场合与时间预算为停止条件。"""

from __future__ import annotations

from typing import Any

from .engine import Halt, ScriptResult, ScriptRun, WorldConsole, _dialog_texts
from .movement import _run
from .timing import POLL_FRAMES

_WALK = "walk"


def advance_dialog(console: WorldConsole, max_presses: int = 30) -> ScriptResult:
    """推进当前对话框到底：反复按 a 直到画面回野外（对话关闭）或出选项 / 进战斗。

    - 三框对话收完回野外 → `ok`；
    - 预算内推不完 → `still_talking`；
    - 中途出选项框 → `choice_presented`（冻结，绝不代选）；
    - 进战斗 → `battle_started`。
    """
    run = _run(console, budget=max_presses)
    run.dialog.ingest(console.read().dialog_text)
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
