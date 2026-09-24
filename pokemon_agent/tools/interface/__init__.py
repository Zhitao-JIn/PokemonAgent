"""tools/interface 包统一出口：`tools` 层对外的端口协议——三张整口
（`GameToolPort`/`MemoryToolPort`/`TraceToolPort`）＋ brain 那族的八张单方法口
（`PlanPort`/`ChoosePort`/`DecomposePort`/`JudgePort`/`ReflectPort`/`VerifyPort`/`SummarizePort`/
`TaskSummarizePort`，0922 185 从 `BrainToolPort` 总口拆出）——harness 认识的工具门面。

它们原来跟实现平级住在 `tools/ports.py`（更早以前在顶层
`pokemon_agent/interfaces/tools/`）。搬进 `interface/` 是因为**出口**而不是
因为文件放哪一级：`tools/__init__.py` 这个统一出口必须导出四个插件，而
`pokemon_agent.tools.interface` 是 `pokemon_agent.tools` 的子模块——Python
要 import 子模块就必先把父包的 `__init__` 跑完，于是"只要有人从
`pokemon_agent.tools` 拿一张协议，四个插件全被请来"。分家之后
`from pokemon_agent.tools.interface import GameToolPort` 不再拖任何实现。

**立即加载，不需要懒加载**：这四张协议只依赖 `schemas.harness` 的信封类型
（实测信封侧零 `tools.*`），`schemas.harness` 对 `tools/` 没有反向依赖——
不存在 `world/interface`/`brain/interface` 那种"schemas 回头要数据形状"的
初始化顺序回环。所以这里不做 `__getattr__`，全部立即导入。

**本包只装抽象，不装实现**：四个插件住在上一层的 `brain_tool.py`/
`game_tools.py`/`memory_tool.py`/`trace/`（checkpoint 那一个已在步 5b 解散，
随后存档链整体删除——本层已无任何存档相关的 Port 与实现），由
收窄后的 `pokemon_agent.tools` 按需懒加载。本包**不**顺手 re-export 它们，
否则这次拆分就白做了。

**不预建 `domain/`**：这四张协议的签名完全由信封类型和标量构成，今天没有
任何一张属于自己的数据形状；沿用 `world`/`trace` 的判据——有专属形状才开
子包。现状见 `docs/spec/tools/SPEC.md` 一、二节。

**`ModelCall` 为什么不在这里**：它的家在 `schemas/harness`（跟 `ModelCallLog`
一起，住在 `communication/ModelCall.py`——主读者是带 `calls` 字段的信封）
——`schemas.harness` 是"harness 唯一认识的那一层"，`ModelCall` 必须以信封
字段的形式从这里出去。放进本包会立刻回环：本包的 `ports.py` 要
`from pokemon_agent.schemas.harness import …`，而 `schemas.harness` 的
信封要 `ModelCall`——两条依赖正面相撞。2026-09-13 试过一轮，实测炸在
`ImportError: partially initialized module`。
"""

from __future__ import annotations

from .ports import (
    ChoosePort,
    DecomposePort,
    GameToolPort,
    JudgePort,
    MemoryToolPort,
    PlanPort,
    ReflectPort,
    SummarizePort,
    TaskSummarizePort,
    TraceToolPort,
    VerifyPort,
)

__all__ = [
    "ChoosePort",
    "DecomposePort",
    "GameToolPort",
    "JudgePort",
    "MemoryToolPort",
    "PlanPort",
    "ReflectPort",
    "SummarizePort",
    "TaskSummarizePort",
    "TraceToolPort",
    "VerifyPort",
]
