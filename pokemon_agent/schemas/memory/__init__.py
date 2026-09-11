"""记忆层产出的契约：三类被持久化的记忆记录形状（单步 / 跨局 / 对象事件）。

**物理位置**：这三个类曾经短暂搬去 `pokemon_agent/memory/datastore/`（当作
"数据形状归它自己的模块"处理），但 `memory/ports.py` 的 `MemoryStorePort`
完全不透明（只认 `metadata`/`payload` 两个裸字段的协议，见
`pokemon_agent/memory/__init__.py` 顶部说明），从来不需要知道这三个类具体
长什么样——只有 tool 层（`tools/memory_tool.py`）和各自的组装方
（`brain.brain.py::reflect()`、`harness/object_interactions.py`）才认识
它们的字段。按"数据形状只有在某个模块的 Port/实现真的需要构造或消费它的
具体样子时，才归那个模块自己"这条边界，它们不属于 `memory/`，物理上归回
这里——本项目自己的跨层契约层。

本文件是 `schemas/memory/` 的统一出口，只做 re-export、不定义任何实体；
消费方写 `from pokemon_agent.schemas.memory import X`，不深到 datastore/
子目录的模块文件。
"""

__all__ = [
    "SCENE_ANY",
    "SNAPSHOT_BLIND",
    "EpisodeMemory",
    "ObjectDialogEvent",
    "ObjectFactEvent",
    "ObjectStillEvent",
    "ObjectWarpEvent",
    "StepMemory",
    "dedup_snapshots",
    "render_sequence",
]

from .datastore import (
    SCENE_ANY,
    SNAPSHOT_BLIND,
    EpisodeMemory,
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
    StepMemory,
    dedup_snapshots,
    render_sequence,
)
