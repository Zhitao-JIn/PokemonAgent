"""trace 自己的词表：`EventType`。

**唯一留下的东西**，其余的都搬走或删了：

- `TraceEvent` → `pokemon_agent.schemas.harness.domain.trace_event`：它是两个
  信封的字段类型（跨层数据形状），契约层不许反向依赖实现包；
- ~~`Source` + `SourceName`~~ → **0913 晚删除**：生产者这一维（"这条事件由哪条
  链产出"）整体下线。链路名现在由 `kind`（`decide_call`…）与 `link` 承载，
  映射在 `tools/trace/render.py`；
- ~~`TRACE_SCHEMA_VERSION`~~ → **0914 删除**（封套改造）：它此前是落盘格式版本号，
  但**全 run 恒 `5`、零读方**，而且两份同值副本（这里 + `schemas/harness/domain/
  trace_event.py`）要人工同步。删掉它不会让"老数据被静默读错"——形状变到这个
  程度，旧 json 缺 `uuid`/`kind`/`meta`/`content`，解析时**当场失败**
  （`store._scan_events` 跳过残文件），不再是"少一个字段就当它空的"。

**`EventType` 与 `TraceKind` 不是同一个概念，别合并**：`TraceKind` 是 harness
声明"我记哪一笔账"（各节点各自声明），住 `schemas/harness/domain/`；
`EventType` 是**这条记录的粗类**——它回答"这条记录相对世界/模型站在哪个位置"，
数量极小（7 个）。两者的对应关系是"每个 kind 恰好落一个 type"，由渲染层给出；
封套两个都留：`type` 供廉价过滤，`kind` 供精确指认。
"""

from __future__ import annotations

from typing import Literal


class EventType:
    """trace 事件种类。**是字符串常量，不是枚举**（0913 降级）。

    **收敛原则**：type 只回答"这条记录是什么种类"，**与链路正交、数量极小**；
    "哪个节点/哪类产物"的语义全部归 `kind`。能通过"换一条链路 type 不变"测试的
    只有 `MODEL_CALL`/`ERROR` 两个，其余五个是承认"领域本质单源"的产物种类
    （VIEW 只来自感知、ACT 的 executed 只来自 world 等）——种类名描述的是记录
    相对世界/模型的位置，不是写它的节点。

    取值见 `EventTypeName`。
    """

    MODEL_CALL = "model_call"  # 一次外部模型交互的账（七条链共用，区分在 kind）
    ERROR = "error"  # 一个失败（call_failed / call_exhausted / summary_parse_error）
    LLM_OUTCOME = "llm_outcome"  # 一次 LLM 交互后结构化出的产物（与 MODEL_CALL 配对）
    VIEW = "view"  # 世界帧（视觉）的记录：kind ∈ {observe, after_action}
    ACT = "act"  # 动作域记录：kind ∈ {do_action, get_action_space, stall_check}
    MEMORY_IO = "memory_io"  # 记忆子系统一次读或写：kind ∈ {read_*, write_*}
    LIFECYCLE = "lifecycle"  # 流程边界与推进（run/episode 边界 + 局内 step 刻度）


EventTypeName = Literal[
    "model_call",
    "error",
    "llm_outcome",
    "view",
    "act",
    "memory_io",
    "lifecycle",
]
"""`EventType` 的合法值域（**类型级表达只有这一处**）。"""
