"""trace 眼里的"一条记录"是什么形状。

`Event` 是 `Protocol`，**trace 不持有任何一个具体类**——它只声明"我记账时需要
什么"，任何满足这些属性的对象都能交进来。项目侧那件（`schemas/harness/domain/
trace_event.py::TraceEvent`）与 trace 自己的 `_Event` 都是**结构化满足**，
既不需要显式继承、也不需要逐字段的副本。

    Event           一条事件记什么——`store.py` 真的读/真的算的那六样。

**为什么要有 `Event` 协议**：`TraceEvent` 是**跨层数据形状**（它出现在
`FromHarnessToReviewerAuditReq` 等信封里），按"契约层不能被实现层反向依赖"
它必须住在 `schemas/`。但 `store.py` 真的要在内部构造/解析事件——两种诉求的
交点就是这个协议：trace 说"给我一个长这样的东西"，项目交来它的 `TraceEvent`。

`kind`/`type`/`meta`/`content` 的值域由**声明方**定义，trace 不认识——它只保证
按时间记账（见 `TracePort` 的 docstring）。**`meta` / `content` 在盘上是 JSON
字符串**，trace 不解释里面装了什么。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Event(Protocol):
    """一个事件的最小形状：**trace 记账真正需要的六样**。

    这六个属性是 `store.py` 全部读点与算法的输入，多一个都不需要：

    | 属性 | trace 拿它干什么 |
    |---|---|
    | `uuid` | 落盘（就是文件名）；扫盘时按它去重 |
    | `ts` | 排序（`(ts, uuid)` 升序）、落盘 |
    | `kind` | 落盘（本类**不解释**它的取值——那是声明方的事） |
    | `type` | 落盘（同上） |
    | `meta` | 落盘随行；**按交集筛选时读它**（`read_events` 的 `meta` 参数） |
    | `content` | 落盘随行 |
    """

    uuid: str
    """本次事件的唯一标识，与文件名同值。"""

    ts: float
    """Unix 时间戳（秒）。排序依据。"""

    kind: str
    """账名（裸 `str`，取值由声明方定义）。"""

    type: str
    """事件种类（裸 `str`，取值由声明方定义）。"""

    meta: str
    """签名信息的 **JSON 字符串**（`{source, run_id, episode_id, step}` 那一族）。"""

    content: str
    """账本体的 **JSON 字符串**。"""
