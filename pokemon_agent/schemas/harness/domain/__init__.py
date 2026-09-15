"""`schemas/harness/domain` 包统一出口：harness 自己声明的领域词汇。

- `TraceKind` —— harness 的**账目词表**（各节点声明"我记哪一笔账"）；
- `TraceEvent` —— 一条已落盘的事件（跨层数据形状：两个信封的字段类型）；
- `GoalEntry` / `GoalStatus` —— run 级目标表的一行（`RunState.plan` 的元素）。

`TraceEvent` 是 0913 下午从 `pokemon_agent/trace/datastore/` 搬来的：它出现在
信封里，按"契约层不许反向依赖实现包"必须住这边。判据见 `AGENTS.md` 铁律 2。

`GoalEntry` 是 0914 控制台改造新增：它取代了 `RunState` 上原先的两个平行列表
（`goals` + `attempts`），把"状态"贴到目标自己身上。见
`docs/PLAN_console_reviewer.md` §4。

**这里不许 import `pokemon_agent.trace`——一个 int 也不行**：一 import 就成环
（`schemas.harness` → `trace` → `trace.store` → `schemas.harness.domain`（半加载）
→ `ImportError`）。唯一为此而"本地声明一份"的东西（`TRACE_SCHEMA_VERSION`）
0914 已随封套改造整个删掉——落盘格式版本号零读方、且两份同值副本要人工同步；
形状变到缺 `uuid`/`kind`/`meta`/`content` 就会解析失败，不再需要一枚版本章
（见 `trace/datastore/trace_event.py` 的说明）。

`Source` 曾在同一处，已**整个删除**（0913 晚）：生产者维度（"这条事件由哪条链
产出"）与 `kind` 记的是同一件事，顶层再挂一个字段是第二份真相。链路名现在由
七个 `*_CALL` 的 `kind` 与错误账的 `content.link` 承载；**谁发的**那条维度 0914
改由 `meta.source` 回答（那是"位置"，不是"链路"）。

只做 re-export、不定义任何实体。
"""

from __future__ import annotations

from .goal_entry import GoalEntry, GoalStatus
from .trace_event import TraceEvent
from .trace_kind import TraceKind

__all__ = ["GoalEntry", "GoalStatus", "TraceEvent", "TraceKind"]
