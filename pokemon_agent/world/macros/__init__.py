"""宏执行器（world）：接管场合里 JEV 调用的宏，一个宏把一件多步操作执行到底。

出口：`macro_specs(scene)`（本场合能调哪些宏，给动作空间）、
`run_macro(console, name, args)`（执行）、`takeover_view(scene, text, mem, rom)`
（接管场合的视图，给观测）。骨架在 `engine.py`，各场合一个文件。
"""

from __future__ import annotations

from ..interface import MacroOutcome, MacroSpec, Memory, ScreenText, TakeoverView, TaskScene
from .bag import BAG_MACROS, bag_view
from .battle import BATTLE_MACROS, FAINT_MACROS, battle_view, faint_view
from .engine import Console, MacroDef
from .engine import run_macro as _run
from .learn_move import LEARN_MACROS, learn_view
from .naming import NAMING_MACROS, naming_view
from .party import PARTY_MACROS, party_view
from .pc import PC_MACROS, pc_view
from .shop import SHOP_MACROS, shop_view

MACROS: dict[TaskScene, dict[str, MacroDef]] = {
    TaskScene.SHOP_ITEMS: SHOP_MACROS,
    TaskScene.NAMING: NAMING_MACROS,
    TaskScene.BATTLE_MENU: BATTLE_MACROS,
    TaskScene.FAINT_SWITCH: FAINT_MACROS,
    TaskScene.BAG: BAG_MACROS,
    TaskScene.PARTY: PARTY_MACROS,
    TaskScene.PC: PC_MACROS,
    TaskScene.LEARN_MOVE: LEARN_MACROS,
}
"""各接管场合的宏。"""


def macro_specs(scene: TaskScene) -> list[MacroSpec]:
    """本场合能调的宏的签名；没有宏的场合为空列表。"""
    return [m.spec for m in MACROS.get(scene, {}).values()]


def run_macro(console: Console, name: str, args: dict[str, str | int]) -> MacroOutcome:
    """执行一个宏（见 `engine.run_macro`）。"""
    return _run(console, MACROS, name, args)


def takeover_view(
    scene: TaskScene, text: ScreenText, mem: Memory, rom: bytes
) -> TakeoverView | None:
    """接管场合的视图；还没有宏的场合为 None。"""
    if scene is TaskScene.SHOP_ITEMS:
        return shop_view(mem, rom)
    if scene is TaskScene.NAMING:
        return naming_view(text, mem)
    if scene is TaskScene.BATTLE_MENU:
        return battle_view(mem)
    if scene is TaskScene.FAINT_SWITCH:
        return faint_view(mem)
    if scene is TaskScene.BAG:
        return bag_view(mem)
    if scene is TaskScene.PARTY:
        return party_view(mem)
    if scene is TaskScene.PC:
        return pc_view(mem)
    if scene is TaskScene.LEARN_MOVE:
        return learn_view(mem)
    return None


__all__ = ["Console", "macro_specs", "run_macro", "takeover_view"]
