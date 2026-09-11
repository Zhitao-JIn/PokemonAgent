"""world 包：`WorldPort` 的实现——PyBoy 模拟器与视觉感知的粘合层。

- `interface/`：这个子系统的港口 + 数据 schema——协议（`world_port.py` 的
  `WorldPort`、`memory.py` 的 `Memory`）和数据形状（`domain/facts.py` 的
  `Facts`——`Scene`/`Overlay`/`Landmark` 都是它的内部类；`domain/screen_state.py`
  的 `ScreenState`；`domain/terrain_map.py` 的 `TerrainMapFromRam`）都在这里，
  跟"怎么读/怎么算"的实现物理分开
- `pyboy_world.py`：`PyBoyWorld`——模拟器生命周期、按键链、感知调度
- `ram.py`：从模拟器内存直接读地形/朝向/地标（`read_terrain` 等），产出
  `interface` 里定义的 `TerrainMapFromRam`
- `frame_slot.py`：`FrameSlot`——实时画面管道的槽位

本文件是统一出口：消费方只写 `from pokemon_agent.world import X`，不深到模块文件。

**`interface/` 立即加载，其余懒加载。** `interface/` 只有协议定义和 pydantic
schema，不碰 PyBoy；`pyboy_world.py` 一整条链会拖着 `from pyboy import PyBoy`
这个重依赖，而且它自己又要 `from pokemon_agent.interfaces import VisionProvider`——
如果这里在包初始化时就把它也一并导入，`pokemon_agent.interfaces`（几乎所有模块的
必经之路，且它自己要 re-export `WorldPort`）跟这个包之间就会形成真正的循环导入：
`interfaces.__init__` → `world.interface`（触发 `world/__init__.py` 全量执行）→
（若这里也急着导 `pyboy_world.py`）→ `interfaces`（还没初始化完）。`__getattr__`
把这几个重名字改成按需导入，`from pokemon_agent.world import X` 用起来和之前
一模一样，只是不再是包初始化时就全量加载。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .interface import OVERLAY_ACTIONS, Facts, Memory, ScreenState, TerrainMapFromRam

if TYPE_CHECKING:
    from .frame_slot import FrameSlot
    from .interface import WorldPort
    from .pyboy_world import PyBoyWorld, parse_screen
    from .ram import read_facing, read_passable, read_screen_tiles, read_terrain

__all__ = [
    "Facts",
    "FrameSlot",
    "Memory",
    "OVERLAY_ACTIONS",
    "PyBoyWorld",
    "ScreenState",
    "TerrainMapFromRam",
    "WorldPort",
    "parse_screen",
    "read_facing",
    "read_passable",
    "read_screen_tiles",
    "read_terrain",
]

_LAZY: dict[str, tuple[str, str]] = {
    "WorldPort": (".interface", "WorldPort"),
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
