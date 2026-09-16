"""trace 包：事件流的存储实现 + 自己的港口协议 + 形状协议。

    interface/  `TracePort`（协议）与 `Event`（形状协议）
    store.py    `TracePort` 的实现：一条事件一个 json 文件（文件名是时间递增 uuid）
    datastore/  `_Event`（私有实现）与 `EventType`（粗类词表）

**一条事件一个 json、全平铺在落盘根下**（0916）：不按 run 分层、也没有
`events/` 这一层，缺省根是启动目录下的 `tracelog/`。"读哪一批"由
`read_events(meta=…)` 的交集匹配回答。

**本包对 `pokemon_agent` 其余部分零 import**——这是 trace 被当作**独立第三方
模块**对待的那条边界的字面含义："拷走即可复用"。

0913–0914 期间陆续搬走/下线的几件（判据都是"归属看谁消费"）：

- `TraceKind` → `schemas.harness`：harness 的账目词表，消费者是 harness 的节点；
- `TraceEvent` → `schemas.harness.domain`：跨层数据形状（出现在信封里），
  契约层不许反向依赖实现包；
- ~~`Source` + `SourceName`~~ → **已删**：生产者维度整体下线；
- ~~`PersistedEvent` / `project` 钩子 / `event_sink` / 截图副本 / `read_screenshot`~~
  → **已删**：落盘形状不再需要项目侧投影；
- ~~`TRACE_SCHEMA_VERSION`~~ → **已删**（0914）：恒 `5`、零读方、要人工同步两份；
- ~~`event_id` / `read_event()` / `frame_png`~~ → **已删**（0914 封套改造）：
  前两个的唯一读方是"取那一帧"，而画面的落盘真源搬到了 `memory/step_memory/`
  的 `before_frame`/`after_frame`。

留在这里的是**真的被 `store.py` 消费**的一件：`EventType`（粗类词表）。

事件 `kind`/`type`/`content` 的格式规则按"harness 解耦"方案住在
`tools/trace/render.py`——组装是 tool 层的处理职责，本模块只做存储。

本文件同时是统一出口：`TracePort`/`LocalTrace`/`Event` 都从这里 re-export，
消费方只写 `from pokemon_agent.trace import LocalTrace, TracePort`。
"""

from .datastore import EventType
from .interface import Event, TracePort
from .store import LocalTrace, new_event_uuid

__all__ = [
    "Event",
    "EventType",
    "LocalTrace",
    "TracePort",
    "new_event_uuid",
]
