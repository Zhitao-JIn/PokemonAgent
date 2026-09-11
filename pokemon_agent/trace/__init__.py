"""trace 包：事件流的存储实现 + 自己的港口协议与账目词表。

    interface/  `TracePort`（协议）+ `TraceKind`（账目种类）——原来分别放在
                顶层 `interfaces/trace/` 和 `schemas/trace/domain/`，这次一起
                搬进来，跟实现同住一包（`pokemon_agent/interfaces/` 这次整个
                撤销，不再保留 re-export 薄壳）
    store.py    `TracePort` 的实现：一条事件一个 json 文件 + 截图便利副本

事件 payload 的格式规则（原 `utils.py`）按"harness 解耦"方案迁去了
`tools/trace_render.py`——payload 组装是 tool 层的处理职责，本模块只做
存储：只依赖 schemas，不依赖任何调用方的领域逻辑。

本文件同时是统一出口：`TraceKind`/`TracePort`/`LocalTrace` 与截图读取从这里
re-export，消费方只写 `from pokemon_agent.trace import LocalTrace, TraceKind,
TracePort`。
"""

from .interface import TraceKind, TracePort
from .store import LocalTrace, read_screenshot, screenshot_filename

__all__ = [
    "LocalTrace",
    "TraceKind",
    "TracePort",
    "read_screenshot",
    "screenshot_filename",
]
