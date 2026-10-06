"""脚本能力目录（P5 统一能力掩码）：**14 条脚本条目的唯一真源**。

`compute_action_space()`（world 侧）与 `mcpclient/game_tools.py::_mask`（tool 层）
都从这里取条目与可用性——**可用性规则只写这一份**，两处消费方不许各抄一份。

条目形状与宏对齐（`ActionEntry`，`kind="script"`）：模型在选择面上不分键 / 宏 /
脚本，一次选择 `名字 ∈ 掩码 且 enabled`；脚本与宏的差异只在**载荷**（参数签名 +
适用场合说明）与**执行通道**（宏 = world 场合内执行到底；脚本 = 跨场合任务链，
一次调用占 harness 账一步）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..interface.domain import ActionEntry, MacroParam
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

if TYPE_CHECKING:  # 只为标注：脚本函数签名统一是 (console, **args) -> ScriptResult
    from .engine import ScriptResult, WorldConsole

# ---- 14 条脚本条目（名字 = MCP 面的 tool 名，一脚本一 API）----

_SCRIPT_SPECS: tuple[ActionEntry, ...] = (
    ActionEntry(
        kind="script",
        name="face_direction",
        params=[MacroParam(name="direction", type="str", description="north/south/west/east")],
        description="转身面朝一个方向（已面向则不动）。适合按键前的姿势准备。",
    ),
    ActionEntry(
        kind="script",
        name="walk_to_adjacent",
        params=[MacroParam(name="direction", type="str", description="north/south/west/east")],
        description="向相邻格走一步；被挡报 blocked。适合只需挪一格的微调。",
    ),
    ActionEntry(
        kind="script",
        name="walk_to",
        params=[
            MacroParam(name="x", type="int"),
            MacroParam(name="y", type="int"),
            MacroParam(name="max_steps", type="int", default=200),
        ],
        description="走到本图坐标 (x, y)（自动绕行，被挡/不收敛如实上报）。适合跨半张图的移动。",
    ),
    ActionEntry(
        kind="script",
        name="circle_walk",
        params=[
            MacroParam(name="laps", type="int"),
            MacroParam(name="extent", type="int", default=1),
        ],
        description="绕圈走满 laps 圈回到起点。适合踩草丛刷遇怪或来回巡逻。",
    ),
    ActionEntry(
        kind="script",
        name="bounce_in_tall_grass",
        params=[MacroParam(name="steps", type="int", default=30)],
        description="在草丛里来回蹦直到遇怪（进战斗即成功）或步数用完。适合刷野生怪。",
    ),
    ActionEntry(
        kind="script",
        name="talk_to_adjacent_npc",
        params=[MacroParam(name="direction", type="str", default="", description="缺省=当前朝向")],
        description="和相邻格的 NPC 说完整段话；中途出选项冻结上报。适合固定 NPC 对话。",
    ),
    ActionEntry(
        kind="script",
        name="buy_item",
        params=[MacroParam(name="item", type="str"), MacroParam(name="count", type="int")],
        description="在商店买 count 个 item（限本店在售清单）。仅商店地图可用。",
    ),
    ActionEntry(
        kind="script",
        name="sell_item",
        params=[MacroParam(name="item", type="str"), MacroParam(name="count", type="int")],
        description="在商店卖掉 count 个 item（背包里须有）。仅商店地图可用。",
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
        params=[MacroParam(name="max_presses", type="int", default=30)],
        description="把当前对话框按 a 推进到结束；中途出选项冻结上报。仅在对话框里可用。",
    ),
    ActionEntry(
        kind="script",
        name="wait_until_scene",
        params=[
            MacroParam(name="scene", type="str", description="要等到的场合，如 walk/battle"),
            MacroParam(name="timeout_s", type="int", default=10),
        ],
        description="不按键干等画面变成指定场合（过场/淡入/回血白闪）；超时如实上报。",
    ),
    ActionEntry(
        kind="script",
        name="exit_map",
        params=[MacroParam(name="target_warp", type="int", default=-1)],
        description="沿静态表出口离开当前地图（换图即成功）。适合跨图移动的第一步。",
    ),
    ActionEntry(
        kind="script",
        name="heal_at_center",
        params=[MacroParam(name="max_steps", type="int", default=60)],
        description="在宝可梦中心走到位、对话、确认 YES、把队伍回满血。仅中心地图可用。",
    ),
    ActionEntry(
        kind="script",
        name="open_menu_to",
        params=[
            MacroParam(
                name="target",
                type="str",
                description="POKéDEX/POKéMON/ITEM/SAVE/OPTION/EXIT",
            )
        ],
        description="打开 start 菜单并把光标移到 target 选中。适合进子菜单前的导航。",
    ),
)

SCRIPT_SPECS: dict[str, ActionEntry] = {e.name: e for e in _SCRIPT_SPECS}
"""全部脚本条目（名字 → 条目）。掩码是白名单 + 场合过滤，不直接展开这份表。"""

# ---- 场合可用性（唯一一份规则）----

_WALK_SCRIPTS: frozenset[str] = frozenset(SCRIPT_SPECS)
_DIALOG_SCRIPTS = frozenset({"advance_dialog", "wait_until_scene"})

SCENE_SCRIPTS: dict[str, frozenset[str]] = {
    "walk": _WALK_SCRIPTS,
    "dialog": _DIALOG_SCRIPTS,
}
"""场合 → 此刻可用的脚本名集合。不在表里的场合一律不给脚本
（战斗 / 各菜单 / 接管场合由宏或按键处理，脚本是跨场合任务链，不在那里插手）。"""


def script_entries(scene: str) -> list[ActionEntry]:
    """本场合可用的脚本条目（`compute_action_space` / `game_tools._mask` 共用）。"""
    names = SCENE_SCRIPTS.get(scene, frozenset())
    return [SCRIPT_SPECS[name] for name in SCRIPT_SPECS if name in names]


def script_entry(name: str) -> ActionEntry | None:
    """按名字取脚本条目；不是脚本名为 None。"""
    return SCRIPT_SPECS.get(name)


# ---- 分发：名字 → 脚本函数（`GameTools.execute` 的脚本通道用）----

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
