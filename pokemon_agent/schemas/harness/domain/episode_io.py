"""episode 子图的交界契约：run 递下来什么（`EpisodeInput`）、交回什么（`EpisodeOutput`）。

取代原 `FromRunHarnessToEpisodeHarnessRunReq/Resp`（那是 harness 内部两层之间的
交界，不是第一跳，不该带 From/To）。产出方 harness，住 `schemas/harness/domain/`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task
from pokemon_agent.schemas.memory import EpisodeMemory
from pokemon_agent.world import TaskObservation

from .termination import Settled, Termination


class EpisodeInput(BaseModel):
    """run 的 `act` 派一局时给的全部初值（`dispatch` 写进 `RunState.episode_input`）。

    `goal.max_steps` 是父级建议task数；硬上限由配置budget.episode_max_tasks提供。
    `tasks` 是目标条目带下来的样本冻结任务表：`loop.freeze_episode_plan` 打开时
    `begin_episode` 用它装初始任务表，关着时忽略（自由规划不看它）。
    """

    run_id: str = Field(description="所属 run")
    run_goal: str = Field(description="所属 run 的目标文本")
    episode_id: str = Field(description="本局标识 `{run_id}-ep{n}`")
    goal: Task = Field(description="本局唯一目标（task_id 即目标表条目的 task_id）")
    tasks: list[Task] = Field(
        default_factory=list,
        description="冻结的 task 表（表序 = 派发顺序）；空 = 本局自己拆",
    )
    actions_budget: int | None = Field(
        default=None, ge=0, description="开局剩余的跨局动作额度；None 不限"
    )
    remaining_s: float | None = Field(
        default=None, ge=0, description="派发时剩余运行秒数；None 不限"
    )


class EpisodeOutput(Settled, BaseModel):
    """episode 交回 run 的结算——run 的 `review_and_judge` 据此盖章、判停。"""

    episode_id: str = Field(description="哪一局")
    goal_id: str = Field(description="本局目标的 task_id——盖章回目标表用")
    termination: Termination = Field(description="终止类别（`success` 由它推出：goal_done 即达成）")
    judge_reason: str = Field(
        default="", description="本局判停时的判定依据（review_and_judge 写）；与下面的 reason 分开"
    )
    reason: str = Field(
        default="", description="`episode_done` 里 LLM 写的结论说明；没蒸馏/异常局为空"
    )
    tasks_used: int = Field(ge=0, description="本局派了几个 task")
    acts_used: int = Field(ge=0, description="本局累计按了几个键（统计用，不参与预算）")
    observation: TaskObservation | None = Field(default=None, description="终局帧；异常局为 None")
    memory: EpisodeMemory | None = Field(
        default=None, description="本局蒸出的 EpisodeMemory；没有可蒸 TaskMemory 时为 None"
    )


__all__ = ["EpisodeInput", "EpisodeOutput"]
