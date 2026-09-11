"""世界层产出的契约：一次感知的返回、观测与地点实体、动作空间，
以及地形网格这些世界模型常量。

本文件是 `schemas/world/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.world import X`，不深到 communication/ 等子目录。

**`Scene`/`Overlay`/`OVERLAY_ACTIONS`/`LandmarkInWorld`/`KIND_*` 不在这里**——
它们搬到了 `pokemon_agent.world.interface`（`Facts.Scene`/`Facts.Overlay`/
`OVERLAY_ACTIONS`/`Facts.Landmark`/`Facts.Landmark.KIND_*`），跟着"世界事实长
什么样"这个概念归到 `Facts` 底下了，见那边模块的 docstring。
"""

__all__ = [
    "ActionSpaceForBrain",
    "BOULDER",
    "BUTTON_FACING",
    "DOOR",
    "FACING_STEP",
    "GRASS",
    "GRID_COLS",
    "GRID_ROWS",
    "INTERACT_KEY",
    "ITEM",
    "MAP_CHARS",
    "ObservationFromWorld",
    "PERSON",
    "PerceiveOnceResp",
    "PLAYER_CELL",
    "PLAYER_MARK",
    "PlaceInWorld",
    "SIGN",
    "TERRAIN_MEANING",
    "terrain_legend",
]
from .communication.PerceiveOnceResp import PerceiveOnceResp
from .domain.action_semantics import BUTTON_FACING, FACING_STEP, INTERACT_KEY
from .domain.action_space_for_brain import ActionSpaceForBrain
from .domain.observation_from_world import ObservationFromWorld
from .domain.place_in_world import PlaceInWorld
from .domain.screen_model import (
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
