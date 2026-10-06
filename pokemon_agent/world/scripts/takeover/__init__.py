"""接管脚本（world）：接管场合里的多步操作，一条脚本把一件事执行到底。

接管场合 = 商店、起名、战斗选单、倒下换人、背包、队伍、PC、学招式。骨架在
`engine.py`（回初态 → 按内存校验 → 逐步执行并核对 → 收尾回初态），各场合一个文件。

**对外名 = 场合前缀 + 文件内短名**（`shop_quit` = `shop` + `quit`）：前缀表 `PREFIX`
是唯一的命名规则，各场合文件里只写短名。

出口：`TAKEOVER_SCRIPTS`（对外名 → 定义）、`takeover_entries(scene)`（本场合可调的
条目，给能力目录）、`run_takeover(console, name, args)`（执行，返回 `TakeoverOutcome`）、
`takeover_view(scene, text, mem, rom)`（接管场合的视图，给观测）。
"""

from __future__ import annotations

from dataclasses import replace

from ...interface import ActionEntry, Memory, ScreenText, TakeoverView, TaskScene
from .bag import BAG_TAKEOVERS, bag_view
from .battle import BATTLE_TAKEOVERS, FAINT_TAKEOVERS, battle_view, faint_view
from .engine import Console, TakeoverDef
from .engine import run_takeover as _run
from .learn_move import LEARN_TAKEOVERS, learn_view
from .naming import NAMING_TAKEOVERS, naming_view
from .outcome import TakeoverOutcome, TakeoverReason, TakeoverStatus, TakeoverStep
from .party import PARTY_TAKEOVERS, party_view
from .pc import PC_TAKEOVERS, pc_view
from .shop import SHOP_TAKEOVERS, shop_view

PREFIX: dict[TaskScene, str] = {
    TaskScene.SHOP_ITEMS: "shop",
    TaskScene.NAMING: "naming",
    TaskScene.BATTLE_MENU: "battle",
    TaskScene.FAINT_SWITCH: "faint",
    TaskScene.BAG: "bag",
    TaskScene.PARTY: "party",
    TaskScene.PC: "pc",
    TaskScene.LEARN_MOVE: "learn",
}
"""接管场合 → 对外名前缀。"""

_SHORT: dict[TaskScene, dict[str, TakeoverDef]] = {
    TaskScene.SHOP_ITEMS: SHOP_TAKEOVERS,
    TaskScene.NAMING: NAMING_TAKEOVERS,
    TaskScene.BATTLE_MENU: BATTLE_TAKEOVERS,
    TaskScene.FAINT_SWITCH: FAINT_TAKEOVERS,
    TaskScene.BAG: BAG_TAKEOVERS,
    TaskScene.PARTY: PARTY_TAKEOVERS,
    TaskScene.PC: PC_TAKEOVERS,
    TaskScene.LEARN_MOVE: LEARN_TAKEOVERS,
}
"""各场合文件里按短名登记的定义。"""


def _public(scene: TaskScene, short: str, defn: TakeoverDef) -> tuple[str, TakeoverDef]:
    """短名定义 → (对外名, 签名里也换成对外名的定义)。"""
    name = f"{PREFIX[scene]}_{short}"
    return name, replace(defn, spec=defn.spec.model_copy(update={"name": name}))


REGISTRY: dict[TaskScene, dict[str, TakeoverDef]] = {
    scene: dict(_public(scene, short, defn) for short, defn in defs.items())
    for scene, defs in _SHORT.items()
}
"""接管场合 → {对外名 → 定义}（执行骨架按场合查）。"""

TAKEOVER_SCRIPTS: dict[str, TakeoverDef] = {
    name: defn for defs in REGISTRY.values() for name, defn in defs.items()
}
"""全部接管脚本（对外名 → 定义）。"""


def takeover_entries(scene: TaskScene) -> list[ActionEntry]:
    """本场合的接管脚本条目（签名 + 说明）；非接管场合为空列表。"""
    return [defn.spec for defn in REGISTRY.get(scene, {}).values()]


def run_takeover(console: Console, name: str, args: dict[str, str | int]) -> TakeoverOutcome:
    """在当前接管场合执行一条接管脚本（见 `engine.run_takeover`）。"""
    return _run(console, REGISTRY, name, args)


def takeover_view(
    scene: TaskScene, text: ScreenText, mem: Memory, rom: bytes
) -> TakeoverView | None:
    """接管场合的视图；非接管场合为 None。"""
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


__all__ = [
    "PREFIX",
    "REGISTRY",
    "TAKEOVER_SCRIPTS",
    "Console",
    "TakeoverOutcome",
    "TakeoverReason",
    "TakeoverStatus",
    "TakeoverStep",
    "run_takeover",
    "takeover_entries",
    "takeover_view",
]
