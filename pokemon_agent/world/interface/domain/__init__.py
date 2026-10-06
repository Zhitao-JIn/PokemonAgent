"""world/interface/domain 包统一出口：这个子系统自己的全部数据 schema。

- `Facts`（及其内部类型 Scene/Overlay/Landmark）、`ScreenState`（视觉模型输出）、
  `TerrainMap`（内存读出的地形图）——原来就在这里。
- `Observation`、`ActionSpace`、`PlaceInWorld`、`action_semantics` 的跨模块常量
  （`BUTTON_FACING`/`FACING_STEP`/`INTERACT_KEY`）、`screen_model` 的地形网格常量
  （`GRID_COLS` 等）——原来放在 `schemas/world/domain/`，那是"interfaces/schemas
  集中制"还没撤销时的位置。它们都是 world 子系统自己对外承诺的数据形状，物理上
  归回这里，`schemas/` 不再保留 `world` 子包（它已经没有信封需要放）。
- `VisionDescribeReq` / `VisionDescribeResp`（`vision_describe.py`）——**0913
  深夜十一新增的副本**：world 的 `VisionProvider` 协议要声明这两个形状，
  而它们的原始定义已随"补全协议是 brain 内部协议"搬进 `brain/schemas/`。
  world 不 import brain，于是复制一份自己用；**两份必须保持同构**
  （见该文件 docstring）。

**改名**：`ObservationFromWorld` → `Observation`、`ActionSpaceForBrain` →
`ActionSpace`、`TerrainMapFromRam` → `TerrainMap`——domain 类型不需要 From/To
这类方向性前缀，那是信封才需要的命名（只有信封需要 from/to，domain 里不需要）。

只做 re-export、不定义任何实体，消费方写 `from pokemon_agent.world.interface import
X`（或再经顶层 `pokemon_agent.world` 转一手），不深到这一层的模块文件。
"""

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
    "TaskScene",
    "TerrainMap",
    "TextSource",
    "VisionDescribeReq",
    "VisionDescribeResp",
    "terrain_legend",
    "BagEntry",
    "NamingView",
    "ShopItem",
    "ShopItemsView",
    "TakeoverView",
    "BattleMenuView",
    "FaintSwitchView",
    "MonEntry",
    "MoveEntry",
    "BagView",
    "BoxEntry",
    "LearnMoveView",
    "PartyView",
    "PcView",
]

from .action_entry import ActionEntry
from .action_semantics import BUTTON_FACING, DIRECTION_KEYS, FACING_STEP, INTERACT_KEY
from .action_space import ActionSpace
from .battle_status import BattleStatus, Combatant
from .facts import OVERLAY_ACTIONS, Facts
from .observation import Observation
from .perceived import Perceived
from .place_in_world import PlaceInWorld
from .ram_readout import BagItem, DecodedText, MenuVars, PartyMon, RamReadout, TextSource
from .screen_model import (
    BOULDER,
    DOOR,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    ITEM,
    LEDGE_DOWN,
    LEDGE_LEFT,
    LEDGE_RIGHT,
    MAP_CHARS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SIGN,
    TERRAIN_MEANING,
    terrain_legend,
)
from .screen_state import ScreenState
from .screen_text import ScreenText
from .script_param import ScriptParam
from .takeover_view import (
    BagEntry,
    BagView,
    BattleMenuView,
    BoxEntry,
    FaintSwitchView,
    LearnMoveView,
    MonEntry,
    MoveEntry,
    NamingView,
    PartyView,
    PcView,
    ShopItem,
    ShopItemsView,
    TakeoverView,
)
from .task_observation import TaskObservation
from .task_perceived import TaskPerceived
from .task_scene import TAKEOVER_SCENES, TaskScene
from .terrain_map import TerrainMap
from .vision_describe import VisionDescribeReq, VisionDescribeResp
