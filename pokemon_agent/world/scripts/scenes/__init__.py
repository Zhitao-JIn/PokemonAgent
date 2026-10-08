"""菜单与战斗业务的脚本声明、能力目录和解码视图。

各场合一个文件；所有声明均经 scripts.definitions.run_definition 使用同一个 ScriptRun。
policy.py 提供可组合的初态恢复、严格等待和收尾步骤，是否采用由每条定义决定。
场合前缀是脚本名字的一部分，PREFIX 是唯一命名规则。"""

from __future__ import annotations

from dataclasses import replace

from ...interface import ActionEntry, Memory, ScreenText, TakeoverView, TaskScene
from ..definitions import ScriptDefinition
from .bag import BAG_SCRIPTS, bag_view
from .battle import BATTLE_SCRIPTS, SWITCH_SCRIPTS, battle_view, switch_view
from .learn_move import LEARN_SCRIPTS, learn_view
from .naming import NAMING_SCRIPTS, naming_view
from .party import PARTY_SCRIPTS, party_view
from .pc import PC_SCRIPTS, pc_view
from .shop import SHOP_SCRIPTS, shop_view

PREFIX: dict[TaskScene, str] = {
    TaskScene.SHOP_ITEMS: "shop",
    TaskScene.NAMING: "naming",
    TaskScene.BATTLE_MENU: "battle",
    TaskScene.BATTLE_SWITCH: "switch",
    TaskScene.BAG: "bag",
    TaskScene.PARTY: "party",
    TaskScene.PC: "pc",
    TaskScene.LEARN_MOVE: "learn",
}
"""仅开放脚本的场合 → 对外名前缀。"""

_SHORT: dict[TaskScene, dict[str, ScriptDefinition]] = {
    TaskScene.SHOP_ITEMS: SHOP_SCRIPTS,
    TaskScene.NAMING: NAMING_SCRIPTS,
    TaskScene.BATTLE_MENU: BATTLE_SCRIPTS,
    TaskScene.BATTLE_SWITCH: SWITCH_SCRIPTS,
    TaskScene.BAG: BAG_SCRIPTS,
    TaskScene.PARTY: PARTY_SCRIPTS,
    TaskScene.PC: PC_SCRIPTS,
    TaskScene.LEARN_MOVE: LEARN_SCRIPTS,
}
"""各场合文件里按短名登记的定义。"""


def _public(scene: TaskScene, short: str, defn: ScriptDefinition) -> tuple[str, ScriptDefinition]:
    """短名定义 → (对外名, 签名里也换成对外名的定义)。"""
    name = f"{PREFIX[scene]}_{short}"
    return name, replace(defn, spec=defn.spec.model_copy(update={"name": name}))


REGISTRY: dict[TaskScene, dict[str, ScriptDefinition]] = {
    scene: dict(_public(scene, short, defn) for short, defn in defs.items())
    for scene, defs in _SHORT.items()
}
"""仅开放脚本的场合 → {对外名 → 定义}（执行骨架按场合查）。"""

SCRIPT_DEFINITIONS: dict[str, ScriptDefinition] = {
    name: defn for defs in REGISTRY.values() for name, defn in defs.items()
}
"""全部脚本（对外名 → 定义）。"""


def scene_script_entries(scene: TaskScene) -> list[ActionEntry]:
    """本场合的脚本条目（签名 + 说明）；非仅开放脚本的场合为空列表。"""
    return [defn.spec for defn in REGISTRY.get(scene, {}).values()]


def takeover_view(
    scene: TaskScene, text: ScreenText, mem: Memory, rom: bytes
) -> TakeoverView | None:
    """仅开放脚本的场合的视图；非仅开放脚本的场合为 None。"""
    if scene is TaskScene.SHOP_ITEMS:
        return shop_view(mem, rom)
    if scene is TaskScene.NAMING:
        return naming_view(text, mem)
    if scene is TaskScene.BATTLE_MENU:
        return battle_view(mem)
    if scene is TaskScene.BATTLE_SWITCH:
        return switch_view(mem)
    if scene is TaskScene.BAG:
        return bag_view(mem)
    if scene is TaskScene.PARTY:
        return party_view(mem)
    if scene is TaskScene.PC:
        return pc_view(mem)
    if scene is TaskScene.LEARN_MOVE:
        return learn_view(mem)
    return None


__all__ = [
    "PREFIX",
    "REGISTRY",
    "SCRIPT_DEFINITIONS",
    "scene_script_entries",
    "takeover_view",
]
