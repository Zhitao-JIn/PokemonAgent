"""trace 包：事件流的存储实现。

    store.py    `TracePort` 的实现：一条事件一个 json 文件 + 截图便利副本

事件 payload 的格式规则（原 `utils.py`）按"harness 解耦"方案迁去了
`tools/trace_render.py`——payload 组装是 tool 层的处理职责，本模块只做
存储：只依赖 schemas，不依赖任何调用方的领域逻辑。

本文件同时是统一出口：`LocalTrace` 与截图读取从这里 re-export，
消费方只写 `from pokemon_agent.trace import LocalTrace`。
"""

from .store import LocalTrace, read_screenshot, screenshot_filename

__all__ = [
    "LocalTrace",
    "read_screenshot",
    "screenshot_filename",
]
