"""run 级 human-in-the-loop：harness 递给复核方的审查上下文。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Task
from pokemon_agent.trace import TraceEvent

from .FromRunHarnessToEpisodeHarnessRunResp import FromRunHarnessToEpisodeHarnessRunResp


class FromHarnessToReviewerReviewReq(BaseModel):
    """递给人类的审查上下文：每个 episode 之间，人类看它做决定。

    `outcomes` 是这个 run 已完成的全部结算（按执行顺序，最后一条 = 刚跑完的
    那一层）；`goals` 是当前目标栈（栈顶 = `goals[-1]`，下一层要做的）；
    `last_task` 是刚跑完那一层的目标（`RETRY` 决策需要知道重试什么）；
    `episode_trace` 是刚跑完那一局的**完整** trace（不是全量 run trace）——
    一次请求自带审查所需的全部依据，前端不用再额外请求一次、也不用自己
    维护跨会话的历史缓存（见 `docs/ROADMAP.md`“前后端交互统一”）。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话）")
    outcomes: list[FromRunHarnessToEpisodeHarnessRunResp] = Field(
        description="已完成的 episode 结算，按执行顺序；最后一条 = 刚跑完的",
    )
    goals: list[Task] = Field(
        description="当前目标栈，栈顶 = goals[-1]（下一层要解决的）",
    )
    last_task: Task | None = Field(
        default=None, description="刚跑完那一层的目标（RETRY 时压回栈顶用）"
    )
    episode_trace: list[TraceEvent] = Field(
        default_factory=list,
        description="刚跑完那一局的完整 trace（单 episode，不是全量 run trace）",
    )
