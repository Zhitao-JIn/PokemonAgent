"""world 包：`WorldPort` 的实现——PyBoy 模拟器与视觉感知的粘合层。

- `pyboy_world.py`：`PyBoyWorld`——模拟器生命周期、按键链、感知调度
- `ram.py`：从模拟器内存直接读地形/朝向/地标（`read_terrain` 等）
- `screen_state.py`：`ScreenState`——感知结果的屏幕状态模型
- `frame_slot.py`：`FrameSlot`——实时画面管道的槽位

本文件是统一出口：消费方只写 `from pokemon_agent.world import X`，不深到模块文件。
"""

__all__ = [
    "FrameSlot",
    "Memory",
    "PyBoyWorld",
    "ScreenState",
    "TerrainMapFromRam",
    "parse_screen",
    "read_facing",
    "read_passable",
    "read_screen_tiles",
    "read_terrain",
]
from .frame_slot import FrameSlot
from .pyboy_world import PyBoyWorld, parse_screen
from .ram import (
    Memory,
    TerrainMapFromRam,
    read_facing,
    read_passable,
    read_screen_tiles,
    read_terrain,
)
from .screen_state import ScreenState
