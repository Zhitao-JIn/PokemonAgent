"""交互类脚本（§7.3）：talk_to_adjacent_npc。

对话推进依赖骨架的每步自动采集（`ScriptRun.press` 内做对话增量 ingest 与
三钩子检查），本层只做前置复验、循环控制与终态报告的载荷拼装。
"""

from __future__ import annotations

from typing import Any

from .engine import Halt, ScriptResult, WorldConsole, _dialog_texts
from .movement import BUTTON_OF, DIRECTIONS, STEP_OF, _reject, _run


def talk_to_adjacent_npc(console: WorldConsole, direction: str | None = None) -> ScriptResult:
    """跟面前 NPC 说话：复验面前格（会走，瞬息可变 → `no_target`）→ 按 a →
    循环推进（对话增量由骨架采集）直至回野外；出选项 `choice_presented` 冻结
    （绝不代选）；训练家型 `battle_started` + dialog；按 a 无框 → `no_response`。"""
    direction = direction or console.facing()
    if direction not in DIRECTIONS:
        return _reject(direction)
    run = _run(console, budget=40)
    start = console.pos()
    dx, dy = STEP_OF[direction]
    # ① 面前格复验（对象表实读）。
    if not console.is_npc(start.x + dx, start.y + dy):
        return run.finish(ok=False, code="no_target", extra={"facing": direction})
    # ② 面前可能已让位：按方向键位移了 = 目标不在了。
    run.press(BUTTON_OF[direction])
    if console.pos() != start:
        return run.finish(
            ok=False,
            code="no_target",
            extra={"facing": direction, "final_pos": console.pos().model_dump()},
        )
    try:
        # ③ 按 a 等对话框：不出 → no_response（合法结果）。
        run.press("a")
        if console.scene() != "dialog":
            return run.finish(ok=False, code="no_response", extra={"dialog": _dialog_texts(run)})
        # ④ 循环推进直至回野外；choice / battle 由钩子抛 Halt。
        while True:
            if run.budget <= 0:
                return run.finish(
                    ok=False,
                    code="still_talking",
                    extra={
                        "dialog": _dialog_texts(run),
                        "final_screen_text": console.read().screen,
                    },
                )
            run.budget -= 1
            run.press("a")
            if console.scene() == "walk":
                return run.finish(
                    ok=True,
                    code="ok",
                    extra={
                        "dialog": _dialog_texts(run),
                        "final_screen_text": console.read().screen,
                    },
                )
    except Halt as halt:
        data: dict[str, Any] = {
            "dialog": _dialog_texts(run),
            "final_screen_text": console.read().screen,
        }
        data.update(halt.extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=data)


def interact_facing(console: WorldConsole) -> ScriptResult:
    """跟面前物体交互（招牌 / 石头 / NPC 通用）：按 a → 有对话 → ok 带对话；
    无任何变化（石头 / 空地）→ `no_response`（合法）；出选项 → `choice_presented`
    （绝不代选）；进战斗 → `battle_started`。对象类型判定归对象记忆层，这里不做。"""
    run = _run(console, budget=20)
    try:
        run.press("a")
        scene = console.scene()
        if scene == "dialog":
            return run.finish(
                ok=True,
                code="ok",
                extra={
                    "dialog": _dialog_texts(run),
                    "final_screen_text": console.read().screen,
                },
            )
        if scene == "walk":
            return run.finish(
                ok=False,
                code="no_response",
                extra={"final_screen_text": console.read().screen},
            )
        # 场合变了但不是 walk/dialog（钩子本应已处理 choice/battle/map；兜底）
        return run.finish(ok=True, code="ok", extra={"final_screen_text": console.read().screen})
    except Halt as halt:
        data: dict[str, Any] = {
            "dialog": _dialog_texts(run),
            "final_screen_text": console.read().screen,
        }
        data.update(halt.extra)
        return run.finish(ok=halt.ok, code=halt.code, extra=data)


__all__ = ["interact_facing", "talk_to_adjacent_npc"]
