"""工具层 —— harness 和其他模块之间的那一层：harness 组装 req，tool 做处理。

五个 tool，各对接一个模块：
- `brain_tool.py`（`BrainToolPort`）对接 brain——req 翻译成 brain 原生输入；
- `checkpoint_tool.py`（`CheckpointToolPort`）对接存档/恢复/废弃归档；
- `trace_tool.py`（`TraceToolPort`）对接 trace——按 `TraceKind` 渲染 payload
  再落盘，渲染规则在 `trace_render.py`（payload 字段格式是跨模块契约，
  观测台前端按字段名渲染，变更权在本层）；
- `game_tools.py`（`GameToolPort`）对接 world；
- `memory_tool.py`（`MemoryToolPort`）对接 memory。

分工约定：harness 只负责组装 req（挑字段、声明 kind），tool 对 req 做处理
（不用改就原样转发），模块只返回自己该返回的，tool 把返回处理成新的 resp
——harness 拿到的 resp 形状由 tool 负责，不随模块内部形状漂移。

**五个 Port 协议**（`BrainToolPort`/`CheckpointToolPort`/`GameToolPort`/
`MemoryToolPort`/`TraceToolPort`）原来放在顶层 `pokemon_agent/interfaces/tools/`，
现在跟着"协议物理挨着它自己的实现"这条原则搬到了 `ports.py`——跟 `memory/`
一样走扁平文件（这五个 Port 没有自己专属的 domain schema，不需要
`world/interface` 那种协议/数据形状二级子包），零循环依赖风险，立即加载。

本文件同时是统一出口：消费方只写
`from pokemon_agent.tools import BrainTool, GameTools, MemoryTool, TraceTool`，
或 `from pokemon_agent.tools import BrainToolPort` 这样各自认模块。
"""

__all__ = [
    "BrainTool",
    "BrainToolPort",
    "CheckpointTool",
    "CheckpointToolPort",
    "GameTools",
    "GameToolPort",
    "MemoryTool",
    "MemoryToolPort",
    "TraceTool",
    "TraceToolPort",
]
from .brain_tool import BrainTool
from .checkpoint_tool import CheckpointTool
from .game_tools import GameTools
from .memory_tool import MemoryTool
from .ports import (
    BrainToolPort,
    CheckpointToolPort,
    GameToolPort,
    MemoryToolPort,
    TraceToolPort,
)
from .trace_tool import TraceTool
