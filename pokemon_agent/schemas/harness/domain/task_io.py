"""task 子图的交界契约：episode 递下来什么（`TaskInput`）、交回什么（`TaskOutput`）。

产出方是 harness（episode 的 `act` 装配入参、task 的 `task_done` 产出结算），
所以住 `schemas/harness/domain/`；父子都从这里 import，同一名字只有一条路径。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task
from pokemon_agent.schemas.memory import TaskMemory

from .termination import Settled, Termination


class TaskInput(BaseModel):
    """episode 派一个 task 时给的全部初值。

    task 层的键预算就是 `task.max_steps`（本层独立计数，不再由 episode 按剩余键数裁）。
    **不带帧**：task 的开局帧由它自己 perceive 格的 `sense` 取（每层只在 perceive 取帧）。
    """

    run_id: str = Field(description="所属 run（记忆归属章）")
    episode_id: str = Field(description="所属 episode（记忆按局分组）")
    task: Task = Field(description="本 task：目标、判据、键预算（max_steps）")
    start_step: int = Field(
        ge=0, description="本局键号基数——task 每一帧的步号 = start_step + 本层键数，跨 task 不重号"
    )
    knowledge: list[str] = Field(
        default_factory=list,
        description="episode 层检索到的领域知识全文（与拆解看到的同一份，不筛），"
        "task 内每次决策原样带上",
    )


class TaskOutput(Settled, BaseModel):
    """task 交回 episode 的结算——episode 的 `perceive` 吸收、`review_and_judge` 据此判。"""

    task_id: str = Field(description="哪一个 task")
    termination: Termination = Field(
        description="终止类别（`success` 由它推出：goal_done 即达成）"
    )
    judge_reason: str = Field(
        default="", description="本 task 判停时的判定依据（review_and_judge 写）；与 reason 分开"
    )
    reason: str = Field(default="", description="`task_done` 里 LLM 写的结论说明；没蒸馏时为空")
    steps_used: int = Field(ge=0, description="本 task 按了几个键")
    memory: TaskMemory | None = Field(
        default=None, description="本 task 蒸出的 TaskMemory；没有 ActMemory 可蒸时为 None"
    )


__all__ = ["TaskInput", "TaskOutput"]
