"""脚本能力目录：全部条目、场合可用性与按名分发的唯一真源。

所有脚本交出控制权执行多步操作，共用 ScriptRun 与 ScriptResult。各文件按业务场合组织；
等待、中断、准备和收尾由脚本声明。动作空间与 tool 掩码只消费这一份可用性规则。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..interface.domain import ActionEntry, ScriptParam, TaskScene
from .definitions import run_definition
from .engine import ScriptResult
from .flow import advance_dialog, wait_until_scene
from .interact import interact_facing, talk_to_adjacent_npc
from .menu import open_menu_to
from .movement import (
    bounce_in_tall_grass,
    circle_walk,
    face_direction,
    walk_to,
    walk_to_adjacent,
)
from .navigation import exit_map, heal_at_center
from .shop import buy_item, sell_item
from .takeover import REGISTRY, TAKEOVER_SCRIPTS

if TYPE_CHECKING:  # 只为标注：脚本函数签名统一是 (console, **args) -> ScriptResult
    from .engine import WorldConsole

# ---- 常规脚本条目（名字 = MCP 面的 tool 名，一脚本一 API）----

_SCRIPT_SPECS: tuple[ActionEntry, ...] = (
    ActionEntry(
        kind="script",
        name="face_direction",
        params=[ScriptParam(name="direction", type="str", description="north/south/west/east")],
        description="转身面朝一个方向（已面向则不动）。适合按键前的姿势准备。",
    ),
    ActionEntry(
        kind="script",
        name="walk_to_adjacent",
        params=[ScriptParam(name="direction", type="str", description="north/south/west/east")],
        description="向相邻格走一步；被挡报 blocked。适合只需挪一格的微调。",
    ),
    ActionEntry(
        kind="script",
        name="walk_to",
        params=[
            ScriptParam(name="x", type="int"),
            ScriptParam(name="y", type="int"),
            ScriptParam(name="max_steps", type="int", default=200),
        ],
        description="走到本图坐标 (x, y)（自动绕行，被挡/不收敛如实上报）。适合跨半张图的移动。",
    ),
    ActionEntry(
        kind="script",
        name="circle_walk",
        params=[
            ScriptParam(name="laps", type="int"),
            ScriptParam(name="extent", type="int", default=1),
        ],
        description="绕圈走满 laps 圈回到起点。适合踩草丛刷遇怪或来回巡逻。",
    ),
    ActionEntry(
        kind="script",
        name="bounce_in_tall_grass",
        params=[ScriptParam(name="steps", type="int", default=30)],
        description="在草丛里来回蹦直到遇怪（进战斗即成功）或步数用完。适合刷野生怪。",
    ),
    ActionEntry(
        kind="script",
        name="talk_to_adjacent_npc",
        params=[ScriptParam(name="direction", type="str", default="", description="缺省=当前朝向")],
        description="和相邻格的 NPC 说完整段话；中途出选项冻结上报。适合固定 NPC 对话。",
    ),
    ActionEntry(
        kind="script",
        name="buy_item",
        params=[ScriptParam(name="item", type="str"), ScriptParam(name="count", type="int")],
        description="买 count 个 item（限本店在售清单；钱与背包事后对账）。商店买卖菜单里可用。",
    ),
    ActionEntry(
        kind="script",
        name="sell_item",
        params=[ScriptParam(name="item", type="str"), ScriptParam(name="count", type="int")],
        description="卖掉 count 个 item（背包里须有；钱事后对账）。商店买卖菜单里可用。",
    ),
    ActionEntry(
        kind="script",
        name="interact_facing",
        params=[],
        description="对面前的东西按一次 a 看反应（读招牌、碰石头）；确认无反应也是合法结果。",
    ),
    ActionEntry(
        kind="script",
        name="advance_dialog",
        params=[ScriptParam(name="max_presses", type="int", default=30)],
        description="把当前对话框按 a 推进到结束；中途出选项冻结上报。仅在对话框里可用。",
    ),
    ActionEntry(
        kind="script",
        name="wait_until_scene",
        params=[
            ScriptParam(name="scene", type="str", description="要等到的场合，如 walk/battle"),
            ScriptParam(name="timeout_s", type="int", default=10),
        ],
        description="不按键干等画面变成指定场合（过场/淡入/回血白闪）；超时如实上报。",
    ),
    ActionEntry(
        kind="script",
        name="exit_map",
        params=[ScriptParam(name="target_warp", type="int", default=-1)],
        description="沿静态表出口离开当前地图（换图即成功）。适合跨图移动的第一步。",
    ),
    ActionEntry(
        kind="script",
        name="heal_at_center",
        params=[ScriptParam(name="max_steps", type="int", default=60)],
        description="在宝可梦中心走到位、对话、确认 YES、把队伍回满血。仅中心地图可用。",
    ),
    ActionEntry(
        kind="script",
        name="open_menu_to",
        params=[
            ScriptParam(
                name="target",
                type="str",
                description="POKéDEX/POKéMON/ITEM/SAVE/OPTION/EXIT",
            )
        ],
        description="打开 start 菜单并把光标移到 target 选中。适合进子菜单前的导航。",
    ),
)

SCRIPT_SPECS: dict[str, ActionEntry] = {
    **{e.name: e for e in _SCRIPT_SPECS},
    **{name: defn.spec for name, defn in TAKEOVER_SCRIPTS.items()},
}
"""全部脚本条目（名字 → 条目），常规 + 接管。掩码按场合过滤，不直接展开这份表。"""

# ---- 场合可用性（唯一一份规则）----

_SHOP_SCRIPTS = frozenset({"buy_item", "sell_item"})
_FIELD_SCRIPTS: frozenset[str] = frozenset(e.name for e in _SCRIPT_SPECS) - _SHOP_SCRIPTS
_DIALOG_SCRIPTS = frozenset({"advance_dialog", "wait_until_scene"})
_TAKEOVER_INTERNAL = frozenset({"shop_buy", "shop_sell"})
"""只经 `buy_item` / `sell_item` 组合调用、不单独给模型的接管脚本（外层负责白名单与对账）。"""

SCENE_SCRIPTS: dict[str, frozenset[str]] = {
    "walk": _FIELD_SCRIPTS,
    "dialog": _DIALOG_SCRIPTS,
    "transition": frozenset({"wait_until_scene"}),
    **{
        scene.value: (frozenset(defs) - _TAKEOVER_INTERNAL)
        | (_SHOP_SCRIPTS if scene is TaskScene.SHOP_ITEMS else frozenset())
        for scene, defs in REGISTRY.items()
    },
}
"""场合 → 此刻可用的脚本名集合。walk 给常规脚本、dialog 给对话推进类、transition 给等待。
各接管场合给
本场合的接管脚本（商店另加 `buy_item` / `sell_item`）；不在表里的场合一律不给脚本。"""


def script_entries(scene: str) -> list[ActionEntry]:
    """本场合可用的脚本条目（`compute_action_space` / `game_tools._mask` 共用）。"""
    names = SCENE_SCRIPTS.get(scene, frozenset())
    return [SCRIPT_SPECS[name] for name in SCRIPT_SPECS if name in names]


def script_entry(name: str) -> ActionEntry | None:
    """按名字取脚本条目；不是脚本名为 None。"""
    return SCRIPT_SPECS.get(name)


# ---- 分发：名字 → 脚本函数（`GameTools.execute` 的脚本通道、`WorldConsole.run_script` 共用）----


def _defined_func(name: str) -> Callable[..., ScriptResult]:
    """把一个声明式脚本接到统一按名调用入口。"""

    def run(console: WorldConsole, **args: str | int) -> ScriptResult:
        return run_definition(console, TAKEOVER_SCRIPTS[name], dict(args))

    return run


SCRIPT_FUNCS: dict[str, Callable[..., ScriptResult]] = {
    "face_direction": face_direction,
    "walk_to_adjacent": walk_to_adjacent,
    "walk_to": walk_to,
    "circle_walk": circle_walk,
    "bounce_in_tall_grass": bounce_in_tall_grass,
    "talk_to_adjacent_npc": talk_to_adjacent_npc,
    "buy_item": buy_item,
    "sell_item": sell_item,
    "interact_facing": interact_facing,
    "advance_dialog": advance_dialog,
    "wait_until_scene": wait_until_scene,
    "exit_map": exit_map,
    "heal_at_center": heal_at_center,
    "open_menu_to": open_menu_to,
    **{name: _defined_func(name) for name in TAKEOVER_SCRIPTS},
}


def run_script_by_name(
    console: WorldConsole, name: str, args: dict[str, str | int]
) -> ScriptResult:
    """按名字执行一条脚本（`GameTools.execute` / 测试共用）。未知脚本名当场炸。"""
    func = SCRIPT_FUNCS.get(name)
    assert func is not None, f"unknown script {name!r}"
    return func(console, **args)


__all__ = [
    "SCRIPT_SPECS",
    "SCENE_SCRIPTS",
    "SCRIPT_FUNCS",
    "script_entries",
    "script_entry",
    "run_script_by_name",
]
