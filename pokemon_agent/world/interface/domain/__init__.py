"""world/interface/domain 包统一出口：这个子系统自己的三份数据 schema——
`Facts`（及其内部类型 Scene/Overlay/Landmark）、`ScreenState`（视觉模型输出）、
`TerrainMapFromRam`（内存读出的地形图）——外加 `Facts` 的动作掩码表
`OVERLAY_ACTIONS`。

只做 re-export、不定义任何实体，消费方写 `from pokemon_agent.world.interface import
Facts`，不深到 `.domain.facts` 这层模块文件。
"""

__all__ = ["Facts", "OVERLAY_ACTIONS", "ScreenState", "TerrainMapFromRam"]

from .facts import OVERLAY_ACTIONS, Facts
from .screen_state import ScreenState
from .terrain_map import TerrainMapFromRam
