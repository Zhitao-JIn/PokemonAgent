"""菜单脚本的初态恢复步骤与生命周期策略，共用统一执行器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...interface import ScreenText, TaskScene
from ...scene import BATTLE_ACTIONS, at_start, classify_scene
from ..control_flow import Abort, Halt
from ..execution_types import ScriptReason, ScriptStatus
from ..policies import ScriptPolicy, StableWait
from ..timing import REWIND_LIMIT

if TYPE_CHECKING:
    from ..engine import ScriptRun


def reset_menu(run: ScriptRun) -> ScriptStatus | None:
    """退回主菜单，战斗菜单再归位到FIGHT；离开场合或达到预算时返回具名结局。"""
    for _ in range(REWIND_LIMIT + 1):
        run.settle()
        text = run.screen()
        scene = classify_scene(text, run.mem)
        if scene is not run.scene:
            return ScriptStatus.LEFT_SCENE
        if at_start(text, scene):
            return None
        key = _reset_key(text, scene)
        run.press_screen(key, expect="回初态")
    return ScriptStatus.ABORTED


def _reset_key(text: ScreenText, scene: TaskScene) -> str:
    """完整战斗主菜单先按行列归位；其他画面用B返回上一层。"""
    if (
        scene is TaskScene.BATTLE_MENU
        and text.options == BATTLE_ACTIONS
        and text.has_cursor
        and text.cursor_cell in ((0, 1), (1, 0), (1, 1))
    ):
        return "up" if text.cursor_cell[0] else "left"
    return "b"


def prepare_menu(run: ScriptRun) -> None:
    """进入业务步骤前恢复菜单初态；失败直接停止，不再次恢复。"""
    status = reset_menu(run)
    if status is ScriptStatus.LEFT_SCENE:
        raise Halt("left_scene", extra={"status": status.value, "reason": "回初态时已离开本场合"})
    if status is ScriptStatus.ABORTED:
        raise Abort(ScriptReason.REWIND_LIMIT, "按 B 回不到初态")


def finish_menu(run: ScriptRun) -> None:
    """按声明尝试恢复初态；恢复中止不覆盖原业务结局。"""
    try:
        reset_menu(run)
    except Abort:
        return


def menu_policy(*, rewind_after: bool = True) -> ScriptPolicy:
    """菜单脚本显式选择准备、失败恢复、可选收尾与严格稳定等待。"""
    return ScriptPolicy(
        wait=StableWait(abort_on_timeout=True),
        before=prepare_menu,
        after=finish_menu if rewind_after else None,
        on_error=finish_menu,
        reset=reset_menu,
        record_steps=True,
    )
