"""world/interface 包统一出口：这个子系统的港口（`WorldPort`/`Memory` 协议）+
数据 schema（`Facts`/`ScreenState`/`TerrainMapFromRam`）。

`WorldPort` 原来放在顶层 `pokemon_agent/interfaces/world/`，跟着"协议物理挨着它吐出
的数据形状"这条原则搬到了这里；`pokemon_agent.interfaces` 仍然 re-export 它
（`brain → interfaces ← harness` 的依赖方向不变，只是这一个 Protocol 的物理文件
挪了地方——见 CLAUDE.md）。`Memory`、`Facts`、`ScreenState`、`TerrainMapFromRam`
原来分别定义在 `world/ram.py`、`world/screen_state.py` 这些"实现文档"里——它们是
协议或数据形状，不是"怎么读/怎么算"的实现，所以搬到这里，跟 `WorldPort` 归在
同一个子包下。

**`WorldPort` 是懒加载的，其余都不是**：`world_port.py` 要
`import pokemon_agent.schemas.brain`，那条链可能绕回 `pokemon_agent.schemas.world`
（`ChooseOnceReq`/`ReflectReq` 都拿 `ObservationFromWorld`）——而
`schemas/world/domain/observation_from_world.py` 又要从这里拿 `Facts`。两条依赖
在初始化顺序上正面相撞：`schemas.world` 聚合 `__init__` 走到
`observation_from_world` 那一行时，如果这里连 `WorldPort` 一起立即导入，就会在
`schemas.world` 自己还没跑完的时候被回头要 `ObservationFromWorld`，直接炸成
`ImportError: cannot import name ... from partially initialized module`。
`Memory`（零依赖）、`Facts`/`ScreenState`/`TerrainMapFromRam`（对 `schemas.world`
的依赖都推迟到各自方法体内部现导，见 `domain/terrain_map.py` 的模块 docstring）
本身都不依赖 `schemas.brain`，可以放心立即导入；`WorldPort` 推迟到真的有人
访问 `.WorldPort` 时才导入，两头都不用再对导入顺序小心翼翼。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain import OVERLAY_ACTIONS, Facts, ScreenState, TerrainMapFromRam
from .memory import Memory

if TYPE_CHECKING:
    from .world_port import WorldPort

__all__ = [
    "Facts",
    "Memory",
    "OVERLAY_ACTIONS",
    "ScreenState",
    "TerrainMapFromRam",
    "WorldPort",
]


def __getattr__(name: str):
    if name == "WorldPort":
        from .world_port import WorldPort as _WorldPort

        globals()["WorldPort"] = _WorldPort
        return _WorldPort
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
