"""world 包：`WorldPort` 的实现——PyBoy 模拟器与视觉感知的粘合层。

- `interface/`：这个子系统的港口 + 全部数据 schema——协议（`world_port.py` 的
  `WorldPort`、`memory.py` 的 `Memory`）和数据形状（`domain/` 下的
  `Facts`/`ScreenState`/`TerrainMap`/`Observation`/`ActionSpace`/`PlaceInWorld`/
  `Perceived`，外加一批常量）都在这里，跟"怎么读/怎么算"的实现物理分开
- `pyboy_world.py`：`PyBoyWorld`——模拟器生命周期、按键链、感知调度
- `ram.py`：从模拟器内存直接读地形/朝向/地标（`read_terrain` 等），产出
  `interface` 里定义的 `TerrainMap`
- `prompts/`：world 自己的 prompt 素材（`perceive_screen.md` + 一份自持的
  `load()`/`PromptTemplate`）——这条 LLM 调用不经过 `Brain` 也不经过任何
  Harness 节点，是 `PyBoyWorld` 自己 `load()` 并渲染的，素材因此跟着 world 走
  （0913 从 `tools/prompts/` 搬来，理由见该包 docstring）

本文件是统一出口：消费方只写 `from pokemon_agent.world import X`，不深到模块文件。

**`interface/` 立即加载，其余懒加载。** `interface/`（含 `WorldPort`）现在是
零依赖的纯协议 + pydantic schema，不碰 PyBoy，可以放心立即加载——`WorldPort`
的方法签名已经改成裸字段，不再 `import pokemon_agent.brain`、也不再依赖
`schemas.*`（详见 `world/interface/world_port.py` 的模块 docstring）。
`pyboy_world.py` 一整条链还拖着 `from pyboy import PyBoy` 这个重依赖，继续
懒加载，不需要为了一个重依赖拖慢整个包的 import。（`VisionProvider` 曾经也要
从 `providers` 拿，2026-09-13 已搬进 `interface/`——这一条不再是懒加载的理由。）

**实时画面管道 0913 夜已删**：`world/frame_slot.py`（`FrameSlot`）连同
`PyBoyWorld.latest_frame()`、`GameTools.latest_frame()`、两个
`FromFrontendToGameToolLatestFrame*` 信封一起移除——唯一消费者是 `api.py`
的 SSE 端点，而 `api.py` 0913 晚已删，整条链从此零调用，生产端却仍每帧
`image.copy()`。服务端重建时按需重写，不预留"现成件"。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .interface import (
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
    MAP_CHARS,
    OVERLAY_ACTIONS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SIGN,
    TERRAIN_MEANING,
    ActionSpace,
    Facts,
    Memory,
    Observation,
    Perceived,
    PlaceInWorld,
    ScreenState,
    TerrainMap,
    VisionDescribeReq,
    VisionDescribeResp,
    VisionProvider,
    WorldPort,
    terrain_legend,
)

if TYPE_CHECKING:
    from .pyboy_world import PyBoyWorld, parse_screen
    from .ram import read_facing, read_passable, read_screen_tiles, read_terrain

__all__ = [
    "ActionSpace",
    "BOULDER",
    "BUTTON_FACING",
    "DIRECTION_KEYS",
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
    "PyBoyWorld",
    "SIGN",
    "ScreenState",
    "TERRAIN_MEANING",
    "TerrainMap",
    "VisionDescribeReq",
    "VisionDescribeResp",
    "VisionProvider",
    "WorldPort",
    "parse_screen",
    "read_facing",
    "read_passable",
    "read_screen_tiles",
    "read_terrain",
    "terrain_legend",
]

_LAZY: dict[str, tuple[str, str]] = {
    "PyBoyWorld": (".pyboy_world", "PyBoyWorld"),
    "parse_screen": (".pyboy_world", "parse_screen"),
    "read_facing": (".ram", "read_facing"),
    "read_passable": (".ram", "read_passable"),
    "read_screen_tiles": (".ram", "read_screen_tiles"),
    "read_terrain": (".ram", "read_terrain"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 —— 惰性出口，名字对应哪个类型由 _LAZY 决定
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value  # 缓存：下次直接命中模块属性，不用重新走 __getattr__
    return value
