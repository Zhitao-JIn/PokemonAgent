"""world 统一出口：模拟器、内存观测、动作与世界语义常量。

协议和数据形状立即加载；PyBoy 实现与读取函数按需加载。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .interface import (
    BASIC_KEYS,
    BOULDER,
    BUTTON_FACING,
    DIRECTION_KEYS,
    DOOR,
    FACING_STEP,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    INTERACT_KEY,
    ITEM,
    MAP_CHARS,
    OVERLAY_ACTIONS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SCRIPT_ONLY_SCENES,
    SIGN,
    TERRAIN_MEANING,
    ActionEntry,
    ActionSpace,
    BagEntry,
    BagView,
    BattleMenuView,
    BattleSwitchView,
    BoxEntry,
    Facts,
    LearnMoveView,
    Memory,
    MonEntry,
    MoveEntry,
    NamingView,
    Observation,
    PartyView,
    PcView,
    PlaceInWorld,
    RamReadout,
    ScreenText,
    ScriptParam,
    ShopItem,
    ShopItemsView,
    TakeoverView,
    TaskObservation,
    TaskPerceived,
    TaskScene,
    TerrainMap,
    WorldPort,
    terrain_legend,
)

if TYPE_CHECKING:
    from .pyboy_world import PyBoyWorld
    from .ram import read_facing, read_passable, read_screen_tiles, read_terrain
    from .scene import at_start, classify_scene

__all__ = [
    "ActionEntry",
    "ActionSpace",
    "BOULDER",
    "BASIC_KEYS",
    "BUTTON_FACING",
    "DIRECTION_KEYS",
    "DOOR",
    "FACING_STEP",
    "Facts",
    "GRASS",
    "GRID_COLS",
    "GRID_ROWS",
    "INTERACT_KEY",
    "ITEM",
    "MAP_CHARS",
    "Memory",
    "Observation",
    "OVERLAY_ACTIONS",
    "PERSON",
    "PLAYER_CELL",
    "PLAYER_MARK",
    "PlaceInWorld",
    "PyBoyWorld",
    "RamReadout",
    "SIGN",
    "ScreenText",
    "ScriptParam",
    "SCRIPT_ONLY_SCENES",
    "TERRAIN_MEANING",
    "TaskObservation",
    "TaskPerceived",
    "BagEntry",
    "NamingView",
    "ShopItem",
    "ShopItemsView",
    "TakeoverView",
    "BattleMenuView",
    "BattleSwitchView",
    "MonEntry",
    "MoveEntry",
    "BagView",
    "BoxEntry",
    "LearnMoveView",
    "PartyView",
    "PcView",
    "TaskScene",
    "TerrainMap",
    "WorldPort",
    "at_start",
    "classify_scene",
    "read_facing",
    "read_passable",
    "read_screen_tiles",
    "read_terrain",
    "terrain_legend",
    "overlay_of",
    "W_TILEMAP",
    "W_IS_IN_BATTLE",
    "CHARMAP",
    "read_tiles",
    "read_screen_text",
]

_LAZY: dict[str, tuple[str, str]] = {
    "PyBoyWorld": (".pyboy_world", "PyBoyWorld"),
    "at_start": (".scene", "at_start"),
    "classify_scene": (".scene", "classify_scene"),
    "read_facing": (".ram", "read_facing"),
    "read_passable": (".ram", "read_passable"),
    "read_screen_tiles": (".ram", "read_screen_tiles"),
    "read_terrain": (".ram", "read_terrain"),
    "overlay_of": (".screen_text", "overlay_of"),
    "W_TILEMAP": (".ram", "W_TILEMAP"),
    "W_IS_IN_BATTLE": (".screen_text", "W_IS_IN_BATTLE"),
    "CHARMAP": (".screen_text", "CHARMAP"),
    "read_tiles": (".screen_text", "read_tiles"),
    "read_screen_text": (".screen_text", "read_screen_text"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 —— 惰性出口，名字对应哪个类型由 _LAZY 决定
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
