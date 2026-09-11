"""world 包：`WorldPort` 的实现——PyBoy 模拟器与视觉感知的粘合层。

- `interface/`：这个子系统的港口 + 全部数据 schema——协议（`world_port.py` 的
  `WorldPort`、`memory.py` 的 `Memory`）和数据形状（`domain/` 下的
  `Facts`/`ScreenState`/`TerrainMap`/`Observation`/`ActionSpace`/`PlaceInWorld`/
  `Perceived`，外加一批常量）都在这里，跟"怎么读/怎么算"的实现物理分开
- `pyboy_world.py`：`PyBoyWorld`——模拟器生命周期、按键链、感知调度
- `ram.py`：从模拟器内存直接读地形/朝向/地标（`read_terrain` 等），产出
  `interface` 里定义的 `TerrainMap`
- `frame_slot.py`：`FrameSlot`——实时画面管道的槽位

本文件是统一出口：消费方只写 `from pokemon_agent.world import X`，不深到模块文件。

**`interface/` 立即加载，其余懒加载。** `interface/`（含 `WorldPort`）现在是
零依赖的纯协议 + pydantic schema，不碰 PyBoy，可以放心立即加载——`WorldPort`
的方法签名已经改成裸字段，不再 `import pokemon_agent.brain`、也不再依赖
`schemas.*`（详见 `world/interface/world_port.py` 的模块 docstring）。
`pyboy_world.py` 一整条链还拖着 `from pyboy import PyBoy` 这个重依赖，且要
`from pokemon_agent.providers import VisionProvider`——这跟 `interface/` 无关，
继续懒加载，不需要为了一个重依赖拖慢整个包的 import。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .interface import (
    ActionSpace,
    BOULDER,
    BUTTON_FACING,
    DOOR,
    FACING_STEP,
    Facts,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    INTERACT_KEY,
    ITEM,
    MAP_CHARS,
    Memory,
    Observation,
    OVERLAY_ACTIONS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    Perceived,
    PlaceInWorld,
    SIGN,
    ScreenState,
    TERRAIN_MEANING,
    TerrainMap,
    WorldPort,
    terrain_legend,
)

if TYPE_CHECKING:
    from .frame_slot import FrameSlot
    from .pyboy_world import PyBoyWorld, parse_screen
    from .ram import read_facing, read_passable, read_screen_tiles, read_terrain

__all__ = [
    "ActionSpace",
    "BOULDER",
    "BUTTON_FACING",
    "DOOR",
    "FACING_STEP",
    "Facts",
    "FrameSlot",
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
    "Perceived",
    "PlaceInWorld",
    "PyBoyWorld",
    "SIGN",
    "ScreenState",
    "TERRAIN_MEANING",
    "TerrainMap",
    "WorldPort",
    "parse_screen",
    "read_facing",
    "read_passable",
    "read_screen_tiles",
    "read_terrain",
    "terrain_legend",
]

_LAZY: dict[str, tuple[str, str]] = {
    "FrameSlot": (".frame_slot", "FrameSlot"),
    "PyBoyWorld": (".pyboy_world", "PyBoyWorld"),
    "parse_screen": (".pyboy_world", "parse_screen"),
    "read_facing": (".ram", "read_facing"),
    "read_passable": (".ram", "read_passable"),
    "read_screen_tiles": (".ram", "read_screen_tiles"),
    "read_terrain": (".ram", "read_terrain"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
