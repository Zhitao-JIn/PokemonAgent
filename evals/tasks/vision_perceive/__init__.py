"""perceive 测评：episode 档感知节点（`world.perceive_frame`）产出的 `Facts` 逐字段对真值。

入口 `inspect eval evals/tasks/vision_perceive/task.py`；
不起模拟器，帧来自帧数据集 v2（`evals/data/frames/`）。
"""

from __future__ import annotations

from evals.core.snapshot import SnapshotMemory, snapshot_of

from .schemas import SCORE_KEYS, VISION_FIELDS, FieldVerdict, PerceiveRun
from .scorer import SCENE_TRUTH, judge_facts, perceive_scorer
from .solver import ProviderUnreachable, perceive_sample, perceive_solver

__all__ = [
    "SCENE_TRUTH",
    "SCORE_KEYS",
    "VISION_FIELDS",
    "FieldVerdict",
    "PerceiveRun",
    "ProviderUnreachable",
    "SnapshotMemory",
    "judge_facts",
    "perceive_sample",
    "perceive_scorer",
    "perceive_solver",
    "snapshot_of",
]
