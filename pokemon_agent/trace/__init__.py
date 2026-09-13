"""trace 包：事件流的存储实现 + 自己的港口协议。

    interface/  `TracePort`（协议）——原来放在顶层 `interfaces/trace/`，这次
                搬进来跟实现同住一包（`pokemon_agent/interfaces/` 这次整个
                撤销，不再保留 re-export 薄壳）
    store.py    `TracePort` 的实现：一条事件一个 json 文件 + 截图便利副本

**`TraceKind` 不再住在这一包**（0913 定案）：它是 harness 的账目词表，
消费者是 harness（22 个节点）而不是 trace 的实现，所以搬去了
`pokemon_agent.schemas.harness`。本包不再 re-export 它——需要它的地方写
`from pokemon_agent.schemas.harness import TraceKind`。

事件 payload 的格式规则（原 `utils.py`）按"harness 解耦"方案迁去了
`tools/trace/render.py`——payload 组装是 tool 层的处理职责，本模块只做
存储：**对 `pokemon_agent` 其余部分零 import**（连 `schemas` 都不依赖，
`TracePort` 只从自己的 `datastore/` 拿 `EventType`/`Source`）。这是 trace 被
当作**独立模块**对待的那条边界，机械核对见 `scripts/check_graph_phases.py`
的"trace 自持"一项。

本文件同时是统一出口：`TracePort`/`LocalTrace` 与截图读取，外加
落盘的事件记录形状（`datastore/`，原来放在 `schemas/trace/datastore/`，物理上
归回自己的包）都从这里 re-export，消费方只写 `from pokemon_agent.trace import
LocalTrace, TraceEvent, TracePort`。
"""

from .datastore import TRACE_SCHEMA_VERSION, EventType, Source, TraceEvent
from .interface import TracePort
from .store import LocalTrace, read_screenshot, screenshot_filename

__all__ = [
    "TRACE_SCHEMA_VERSION",
    "EventType",
    "LocalTrace",
    "Source",
    "TraceEvent",
    "TracePort",
    "read_screenshot",
    "screenshot_filename",
]
