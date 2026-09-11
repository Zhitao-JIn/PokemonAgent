"""memory/datastore 包：三类被持久化的记忆记录形状（单步 / 跨局 / 对象事件）。

原来放在 `pokemon_agent/schemas/memory/datastore/`——那是"interfaces/schemas
集中制"还没撤销时的位置。这几个类是 memory 包自己持久化的记录形状，不是
"给别的模块看的信封"，物理上归回 `memory/` 自己，`schemas/` 不再保留
`memory` 子包（它已经没有任何信封需要放）。

只做 re-export、不定义新实体，消费方写 `from pokemon_agent.memory import X`
（顶层 `memory/__init__.py` 会再转一手），不需要深到这一层。
"""

__all__ = [
    "EpisodeMemory",
    "ObjectDialogEvent",
    "ObjectFactEvent",
    "ObjectStillEvent",
    "ObjectWarpEvent",
    "SCENE_ANY",
    "SNAPSHOT_BLIND",
    "StepMemory",
    "dedup_snapshots",
    "render_sequence",
]
from .episode_memory import SCENE_ANY, EpisodeMemory
from .object_memory import ObjectDialogEvent, ObjectFactEvent, ObjectStillEvent, ObjectWarpEvent
from .step_memory import SNAPSHOT_BLIND, StepMemory, dedup_snapshots, render_sequence
