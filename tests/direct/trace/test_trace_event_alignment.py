"""项目侧事件形状与 trace 协议的机械对齐：`TraceEvent` 的字段 == `Event` 的属性。

**为什么这条住在 `tests/direct/trace/` 而不是 `tests/trace/`**：它要同时 import 两边
——`schemas.harness.domain.TraceEvent`（项目侧的跨层数据形状）与 `trace.Event`
（trace 自己声明的协议）。写进 `tests/trace/` 会让那个目录看起来"依赖项目其余部分"，
而 trace 包恰恰以"拷走即可复用、出边为零"为卖点；这份交叉核对属于认识两边的门面层。

**为什么它值钱**：两份定义是**结构化满足**的关系（不继承、不 import 对方），
字段对不上不会报错、只会静默丢字段——`trace/datastore/event.py` 与
`schemas/harness/domain/trace_event.py` 的 docstring 都写着"没有编译器保护"。
`tests/trace/test_trace_event_protocol.py` 守的是协议 ↔ 盘上记录，这一条守的是
协议 ↔ 项目侧形状，两个方向都钉住，"三份定义靠人工同步"才不是一句空话。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness.domain import TraceEvent
from pokemon_agent.trace import Event


def test_trace_event_shape_matches_the_trace_event_protocol() -> None:
    """两边字段名集合相等：多一个说明有一边偷偷加了字段，少一个是丢字段的静默 bug。"""
    project_side = set(TraceEvent.model_fields)
    trace_side = set(Event.__annotations__)

    assert project_side == trace_side, (
        f"项目侧有、协议没有：{sorted(project_side - trace_side)}；"
        f"协议有、项目侧没有：{sorted(trace_side - project_side)}"
    )
