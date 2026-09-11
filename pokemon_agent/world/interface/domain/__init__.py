"""world/interface/domain 包统一出口：这个子系统自己的全部数据 schema。

- `Facts`（及其内部类型 Scene/Overlay/Landmark）、`ScreenState`（视觉模型输出）、
  `TerrainMap`（内存读出的地形图）——原来就在这里。
- `Observation`、`ActionSpace`、`PlaceInWorld`、`action_semantics` 的跨模块常量
  （`BUTTON_FACING`/`FACING_STEP`/`INTERACT_KEY`）、`screen_model` 的地形网格常量
  （`GRID_COLS` 等）——原来放在 `schemas/world/domain/`，那是"interfaces/schemas
  集中制"还没撤销时的位置。它们都是 world 子系统自己对外承诺的数据形状，物理上
  归回这里，`schemas/` 不再保留 `world` 子包（它已经没有信封需要放）。

**改名**：`ObservationFromWorld` → `Observation`、`ActionSpaceForBrain` →
`ActionSpace`、`TerrainMapFromRam` → `TerrainMap`——domain 类型不需要 From/To
这类方向性前缀，那是信封才需要的命名（只有信封需要 from/to，domain 里不需要）。

只做 re-export、不定义任何实体，消费方写 `from pokemon_agent.world.interface import
X`（或再经顶层 `pokemon_agent.world` 转一手），不深到这一层的模块文件。
"""

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
    "terrain_legend",
]

from .action_semantics import BUTTON_FACING, FACING_STEP, INTERACT_KEY
from .action_space import ActionSpace
from .facts import OVERLAY_ACTIONS, Facts
from .observation import Observation
from .perceived import Perceived
from .place_in_world import PlaceInWorld
from .screen_model import (
    BOULDER,
    DOOR,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    ITEM,
    MAP_CHARS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SIGN,
    TERRAIN_MEANING,
    terrain_legend,
)
from .screen_state import ScreenState
from .terrain_map import TerrainMap
