"""项目认识的 trace 事件：本项目的记账约定。

**为什么住在这里**（0913 下午从 `pokemon_agent/trace/datastore/` 搬来）：
`TraceEvent` 是**跨层数据形状**——它出现在信封的字段注解里
（`FromHarnessToReviewerAuditReq.episode_trace`）。契约层不能反向依赖实现包
（`CHANGELOG.md` 深夜七第 5 条），所以它归 `schemas/harness/domain/`。

**与 `trace.interface.Event` 的关系是"结构化满足"，不是继承**：本模块
**不 import `pokemon_agent.trace` 的任何东西**——只是字段结构对得上，
鸭子类型自洽（实测 `isinstance(TraceEvent(...), Event) is True`）。
一旦这里 import 了 trace，`schemas.harness` → `trace` → `trace.store` →
`schemas.harness.domain` 就成了一个真回环，import 时直接炸
（`ImportError: partially initialized module`）。

**六个字段分三组**（0914 封套改造）：

| 组 | 字段 | 谁填 |
|---|---|---|
| 封套 | `uuid`/`kind`/`type`/`ts` | 前三个由 tool 层给；`ts` 归 `store.py` |
| 标签 | `meta` | harness 自报的签名（`source`/`run_id`/`episode_id`/`step`），**JSON 字符串** |
| 正文 | `content` | 该账的内容，**JSON 字符串** |

`uuid` 是文件名，落盘那一刻才生成，所以由 `store.py` 盖。

**0914 删掉的四件**（见 `CHANGELOG.md` 第 100 条）：

- `event_id`（全局单调序号）——它的**唯一非内部读方**是"按 id 取单条事件"，
  而那件事随 `frame_png` 一起下线了。排序改看 `ts`（时间戳进封套之后不再
  是死字段），同毫秒靠 `uuid` 兜底；
- `schema_version`——两份同值副本要人工同步，且全 run 恒 `5`、零读方。
  删掉不会让"老数据被静默读错"：形状变到这个程度，旧 json 缺 `uuid`/`kind`/
  `meta`/`content` 会**当场解析失败**（`store._scan_events` 跳过残文件），
  不再是"少一个字段就当它是空的"那种静默；
- `frame_png`——画面的唯一落盘真相改成 `memory/step_memory/*.json` 里的
  `before_frame`/`after_frame`（那才是模型侧真正读的东西）。**反转 0913 晚
  那个决定**：事件不再自带图，`read_event()` 那条回盘取图的路径整条下线；
- 顶层 `run_id` / `episode_id` / `step`——搬进 `meta`（它们正是"harness 想传的
  签名信息"，不是封套该管的事）。

改动字段必须同步 `trace/datastore/event.py::_Event`——**没有编译器保护**
（结构化满足是隐式的）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    """一条已落盘的项目事件。

    这是 replay / 观测台 / 成本统计 / 失败聚合 / 实验归因的共同底座，
    所以它是**不可变的事件**，不是可变的状态快照——不要往里加"当前状态"
    这类字段，那样就没法重放了。
    """

    uuid: str = Field(
        description="本次事件的唯一标识，**与文件名同值**。由 `store.py` 落盘那一刻盖上"
        "（名字到那时才生成，渲染层拿不到）"
    )
    kind: str = Field(
        description="账名（`TraceKind` 的值）——这是哪笔账。"
        "**tool 层给的**：渲染层按 `req.kind` 原样落，中间没有翻译表"
    )
    type: str = Field(description="事件种类（见 `EventType` 的常量）。**tool 层给的**")
    ts: float = Field(
        description="Unix 时间戳，秒。**排序的唯一依据**（`(ts, uuid)` 升序）"
        "——算延迟与对齐外部日志也用它"
    )
    meta: str = Field(
        default="{}",
        description="harness 自报的**签名信息**，JSON 字符串："
        "`{source, run_id, episode_id, step}`。`source` = 发这条账的位置"
        "（图上节点名，或图外入口名如 `run_entry.new_run`）；"
        "**run 级账沿用项目约定**——`episode_id` 位放 `run_id`、`step` 恒 0",
    )
    content: str = Field(
        default="{}",
        description="这笔账的本体，JSON 字符串。**存在反函数**：能从这串字符"
        "无损还原出源记录的字段。字段名由渲染层定（跨模块契约）",
    )
