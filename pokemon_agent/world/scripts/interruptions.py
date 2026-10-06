"""地图操作脚本选择的中断条件；菜单操作可选择其他条件或不启用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..interface import TaskScene
from ..scene import classify_scene
from .control_flow import Halt
from .policies import ScriptPolicy

if TYPE_CHECKING:
    from .engine import ScriptRun


def battle_started(run: ScriptRun) -> None:
    """进入战斗时停下，将后续决策交回调用方。"""
    text = run.screen()
    if classify_scene(text, run.mem) is TaskScene.BATTLE or text.in_battle:
        raise Halt("battle_started")


def choice_presented(run: ScriptRun) -> None:
    """出现选项时停下；只有选择了本条件的脚本才不继续按键。"""
    text = run.screen()
    if text.has_cursor and text.options:
        raise Halt("choice_presented", extra={"choice": " / ".join(text.options)})


def map_changed(run: ScriptRun) -> None:
    """离开起始地图时停下，并报告新的地图编号。"""
    if run.console.map_id() != run.start_map_id:
        raise Halt("map_changed", extra={"map_id": run.console.map_id()})


def field_policy() -> ScriptPolicy:
    """地图脚本显式选择三种中断，并记录统一世界事件。"""
    return ScriptPolicy(
        interruptions=(battle_started, choice_presented, map_changed),
        collect_world_events=True,
    )
