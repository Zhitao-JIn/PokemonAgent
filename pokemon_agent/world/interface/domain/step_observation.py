"""脚本内每键后的紧凑观察：屏幕、RAM 与面朝物体的只读快照。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .battle_status import BattleStatus
from .facts import Facts
from .place_in_world import PlaceInWorld
from .ram_readout import BagItem, PartyMon
from .task_scene import TaskScene


class RamState(BaseModel):
    """从 RamReadout 摘出的游戏状态，不携带菜单变量与解码诊断。"""

    in_battle: bool
    money: int
    bag: list[BagItem]
    party: list[PartyMon]


class FacingObject(BaseModel):
    """当前朝向相邻格的交互物；无交互物时整项为 None。"""

    kind: str
    place: PlaceInWorld


class StepObservation(BaseModel):
    """一次脚本内按键后的快照；step 从 1 起按本次 ScriptRun 的按键顺序编号。"""

    step: int = Field(ge=0)
    place: PlaceInWorld
    facing: str
    scene: TaskScene
    overlay: Facts.Overlay
    dialog_text: str = ""
    options: list[str] = Field(default_factory=list)
    cursor: str = ""
    screen: str = ""
    ram: RamState | None = None
    facing_object: FacingObject | None = None
    battle_status: BattleStatus | None = None
    settled: bool = True


__all__ = ["FacingObject", "RamState", "StepObservation"]
