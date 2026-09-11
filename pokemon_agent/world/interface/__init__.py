"""world/interface 包统一出口：这个子系统的港口（`WorldPort`/`Memory` 协议）+
全部数据 schema（`domain/` 子包：`Facts`/`ScreenState`/`TerrainMap`/`Observation`/
`ActionSpace`/`PlaceInWorld`/`Perceived`/一批常量）。

`WorldPort` 原来放在顶层 `pokemon_agent/interfaces/world/`，跟着"协议物理挨着它吐出
的数据形状"这条原则搬到了这里；`pokemon_agent/interfaces/` 这个集中注册表已经
整个撤销，消费方直接 `from pokemon_agent.world import WorldPort`。

**`WorldPort` 现在是零依赖的，不再需要懒加载。** 之前 `world_port.py` 要
`import pokemon_agent.brain`（`ActionFromBrain`/`TaskForBrain` 做参数类型）、
`import pokemon_agent.schemas.world.communication.PerceiveOnceResp`（做返回类型），
这两条依赖分别撞过初始化顺序的坑。按"模块间零依赖，只靠裸函数和 tool 层交互"
这条原则（brain/world/memory/trace 互相都不能依赖），`WorldPort` 的方法签名
改成了裸字段（`reset`/`set_task` 收 `task_id`/`goal`/`success_criteria`/
`max_steps`/`initial_state_hint` 五个原始参数，`step` 收
`list[tuple[str, int]]` 的按键段列表），返回值也换成了 world 自己的
`Perceived`（`domain/perceived.py`，不是 schemas 里的信封）。`WorldPort` 因此
可以放心立即导入，不再需要 `__getattr__` 懒加载这层机制。
"""

from __future__ import annotations

from .domain import (
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
    terrain_legend,
)
from .memory import Memory
from .world_port import WorldPort

__all__ = [
    "ActionSpace",
    "BOULDER",
    "BUTTON_FACING",
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
    "Perceived",
    "PlaceInWorld",
    "SIGN",
    "ScreenState",
    "TERRAIN_MEANING",
    "TerrainMap",
    "WorldPort",
    "terrain_legend",
]
