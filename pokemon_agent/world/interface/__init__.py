"""world/interface 包统一出口：这个子系统的港口（`WorldPort`/`Memory` 协议）+
全部数据 schema（`domain/` 子包：`Facts`/`ScreenState`/`TerrainMap`/`Observation`/
`ActionSpace`/`PlaceInWorld`/`Perceived`/一批常量）。

`WorldPort` 原来放在顶层 `pokemon_agent/interfaces/world/`，跟着"协议物理挨着它吐出
的数据形状"这条原则搬到了这里；`pokemon_agent/interfaces/` 这个集中注册表已经
整个撤销，消费方直接 `from pokemon_agent.world import WorldPort`。

**`WorldPort` 现在是零依赖的，不再需要懒加载。** 之前 `world_port.py` 要
`import pokemon_agent.brain`（`Action`/`Task` 做参数类型）、
`import pokemon_agent.schemas.world.communication.PerceiveOnceResp`（做返回类型），
这两条依赖分别撞过初始化顺序的坑。按"模块间零依赖，只靠裸函数和 tool 层交互"
这条原则（brain/world/memory/trace 互相都不能依赖），`WorldPort` 的方法签名
改成了裸字段（`reset`/`set_task` 收 `task_id`/`goal`/`success_criteria`/
`max_steps`/`initial_state_hint` 五个原始参数，`step` 收
`list[tuple[str, int]]` 的按键段列表），返回值也换成了 world 自己的
`Perceived`（`domain/perceived.py`，不是 schemas 里的信封）。`WorldPort` 因此
可以放心立即导入，不再需要 `__getattr__` 懒加载这层机制。

**`VisionProvider` 也在这里（2026-09-13）**：从 `providers/interface/` 搬来
——`world` 是唯一真正调 `describe()` 的模块，"把图片变成文字"就是 world 对外
要的那个能力。协议的归属看**谁消费**，不看谁实现（供应商实现只是恰好两个方法
都实现了）。
"""

from __future__ import annotations

from .domain import (
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
    LEDGE_DOWN,
    LEDGE_LEFT,
    LEDGE_RIGHT,
    MAP_CHARS,
    OVERLAY_ACTIONS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SIGN,
    TAKEOVER_SCENES,
    TERRAIN_MEANING,
    ActionEntry,
    ActionSpace,
    BagEntry,
    BagItem,
    BagView,
    BattleMenuView,
    BattleStatus,
    BattleSwitchView,
    BoxEntry,
    Combatant,
    DecodedText,
    Facts,
    LearnMoveView,
    MenuVars,
    MonEntry,
    MoveEntry,
    NamingView,
    Observation,
    PartyMon,
    PartyView,
    PcView,
    Perceived,
    PlaceInWorld,
    RamReadout,
    ScreenState,
    ScreenText,
    ScriptParam,
    ShopItem,
    ShopItemsView,
    TakeoverView,
    TaskObservation,
    TaskPerceived,
    TaskScene,
    TerrainMap,
    TextSource,
    VisionDescribeReq,
    VisionDescribeResp,
    terrain_legend,
)
from .memory import Memory
from .vision_provider import VisionProvider
from .world_port import WorldPort

__all__ = [
    "ActionEntry",
    "ActionSpace",
    "BOULDER",
    "BagItem",
    "BattleStatus",
    "BUTTON_FACING",
    "DIRECTION_KEYS",
    "DOOR",
    "FACING_STEP",
    "Facts",
    "GRASS",
    "LEDGE_DOWN",
    "LEDGE_LEFT",
    "LEDGE_RIGHT",
    "GRID_COLS",
    "GRID_ROWS",
    "INTERACT_KEY",
    "Combatant",
    "DecodedText",
    "ITEM",
    "MAP_CHARS",
    "Memory",
    "MenuVars",
    "Observation",
    "OVERLAY_ACTIONS",
    "PERSON",
    "PLAYER_CELL",
    "PLAYER_MARK",
    "PartyMon",
    "Perceived",
    "PlaceInWorld",
    "RamReadout",
    "SIGN",
    "ScreenState",
    "ScreenText",
    "ScriptParam",
    "TAKEOVER_SCENES",
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
    "TextSource",
    "VisionDescribeReq",
    "VisionDescribeResp",
    "VisionProvider",
    "WorldPort",
    "terrain_legend",
]
