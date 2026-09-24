"""brain/interface/domain 包：大脑对外契约里内嵌的数据形状。

原来分散在 `schemas/brain/domain/` 下，跟 `world`/`trace`/`providers` 一样，
搬进来跟协议（`brain_port.py` 的 `BrainPort`）同住一包。全部零依赖（只依赖
pydantic），可以放心立即加载。
"""

from __future__ import annotations

from .action import Action, ActionSegment
from .decomposition import Decomposition
from .episode_summary import EpisodeSummary
from .goal import Goal
from .model_call import ModelCall
from .reflection import Reflection
from .results import (
    ChooseResult,
    DecomposeResult,
    JudgeResult,
    PlanResult,
    SummarizeResult,
    VerifyResult,
)
from .run_plan import RunPlan
from .task import Task
from .verify_verdict import VerifyVerdict

__all__ = [
    "Action",
    "ActionSegment",
    "ChooseResult",
    "DecomposeResult",
    "Decomposition",
    "EpisodeSummary",
    "Goal",
    "JudgeResult",
    "ModelCall",
    "PlanResult",
    "Reflection",
    "RunPlan",
    "VerifyVerdict",
    "SummarizeResult",
    "Task",
    "VerifyResult",
]
