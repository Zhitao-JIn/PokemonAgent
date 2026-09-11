"""记忆层产出的契约：三类被持久化的记忆形状（单步 / 跨局 / 对象事件）。

本文件是 `schemas/memory/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.memory import X`，不深到 datastore/ 等子目录。
知识检索的信封（FromHarnessToMemoryToolQueryKnowledge*）归发起方 harness，
见 `schemas/harness/`。
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
from .datastore.episode_memory import SCENE_ANY, EpisodeMemory
from .datastore.object_memory import (
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectStillEvent,
    ObjectWarpEvent,
)
from .datastore.step_memory import SNAPSHOT_BLIND, StepMemory, dedup_snapshots, render_sequence
