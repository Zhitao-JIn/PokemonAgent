"""brain/interface/domain 包：大脑对外契约里内嵌的数据形状。

原来分散在 `schemas/brain/domain/` 下，跟 `world`/`trace`/`providers` 一样，
搬进来跟协议（`brain_port.py` 的 `BrainPort`）同住一包。全部零依赖（只依赖
pydantic），可以放心立即加载。
"""

from __future__ import annotations

from .action import (
    MAX_RATIONALE,
    MAX_SEGMENTS,
    MAX_TIMES,
    Action,
    ActionSegment,
)
from .episode_summary import EpisodeSummary
from .goal import Goal
from .run_plan import RunPlan
from .step_verify import StepVerifyVerdict
from .task import Task

__all__ = [
    "MAX_RATIONALE",
    "MAX_SEGMENTS",
    "MAX_TIMES",
    "Action",
    "ActionSegment",
    "EpisodeSummary",
    "Goal",
    "RunPlan",
    "StepVerifyVerdict",
    "Task",
]
