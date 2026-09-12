"""schemas/memory/datastore 包：被持久化的三类记忆记录的**具体形状**。

**为什么在 `schemas/` 而不是 `memory/`：** `MemoryStorePort`（`memory/ports.py`）
是完全不透明的协议——它写的是 `metadata: dict[str, str]` + `payload: dict`
这两个裸字段，从来不需要知道 `StepMemory`/`EpisodeMemory`/`ObjectFactEvent`
这几个类具体长什么样（`memory/store.py` 的实现同理，只做按 uuid 落盘 + 倒排
索引，不 import 这三个类）。按"一个数据形状只有在某个模块的 Port/实现真的
需要构造或消费它的具体样子时，才归那个模块自己"这条边界，这三个类不满足
条件——只有 **tool 层**（`tools/memory_tool.py`，读写 payload 时要按具体
形状序列化/反序列化）和它们各自的组装方（`brain.reflect()`、
`harness/object_interactions.py`）真正认识这几个类的字段。这正是
`schemas/`（本项目自己的跨层契约层）该管的事，不是 `memory/` 自己的数据形状。

对比：`trace/datastore/trace_event.py`（`TraceEvent`）留在 `trace/` 自己包
里——因为 `TracePort.append()`/`LocalTrace.read_disk_events()` 这两个真实
实现确实要在**内部**构造/解析 `TraceEvent`，不透明的是它的输入（裸字段），
不是它的存储格式；而 `MemoryStorePort` 连存储格式都不关心。

**`StepMemory`/`ObjectFactEvent` 内部对 `Observation`/`PlaceInWorld`
"形状像但类不同"的字段（`StepMemory.Observation`、
`ObjectFactEventBase.Place`）是各自的内部类，不 import
`pokemon_agent.world` 的真身——世界那边的 `Observation`/`PlaceInWorld` 只有
harness/brain（构造这些记录的地方）才直接打交道，这里存的是"long-term 记下
来的样子"，不需要 world 类型的任何行为（`step_toward()`/懒加载校验……），
只需要它的字段。构造方（`brain.brain.py::reflect()`、
`harness/object_interactions.py`）负责把真身 `.model_dump(mode="json")`
拍平后再喂进来。**

只做 re-export、不定义新实体，消费方写
`from pokemon_agent.schemas.memory import X`（顶层 `__init__.py` 会再转一手）。
"""

__all__ = [
    "SCENE_ANY",
    "SNAPSHOT_BLIND",
    "EpisodeMemory",
    "ObjectDialogEvent",
    "ObjectFactEvent",
    "ObjectFactEventBase",
    "ObjectStillEvent",
    "ObjectWarpEvent",
    "StepMemory",
    "StopReason",
    "decision_key",
    "dedup_snapshots",
    "group_by_decision",
    "last_decisions",
    "render_decisions",
    "render_sequence",
]

from .episode_memory import SCENE_ANY, EpisodeMemory
from .object_memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectFactEventBase,
    ObjectStillEvent,
    ObjectWarpEvent,
)
from .step_memory import (
    SNAPSHOT_BLIND,
    StepMemory,
    StopReason,
    decision_key,
    dedup_snapshots,
    group_by_decision,
    last_decisions,
    render_decisions,
    render_sequence,
)
