"""run 级 human-in-the-loop 的协议：每个 episode 之间，人类审查并决定下一步。

`HumanReviewReqFromHarness` 是递给人类的上下文（run 到哪了、各局成败、当前栈、刚跑完的
那一层），`HumanReviewRespFromFrontend` 是人类的决策——**由前端（人机界面）消费/生产**，
后端只定义协议 + 提供"自动继续"的占位实现。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from pokemon_agent.schemas.datastore import TraceEvent
from pokemon_agent.schemas.domain import TaskForHarness

from .harness_episode_outcome import HarnessEpisodeOutcomeResp


class HumanDecision(str, Enum):
    """人类对"下一层怎么办"的决策。"""

    CONTINUE = "continue"
    """继续下一层（默认）。"""
    STOP = "stop"
    """停止整个 run。"""
    RETRY = "retry"
    """重试刚跑完的那一层（把上一层的目标重新压回栈顶）。"""


class HumanReviewReqFromHarness(BaseModel):
    """递给人类的审查上下文：每个 episode 之间，人类看它做决定。

    `outcomes` 是这个 run 已完成的全部结算（按执行顺序，最后一条 = 刚跑完的
    那一层）；`goals` 是当前目标栈（栈顶 = `goals[-1]`，下一层要做的）；
    `last_task` 是刚跑完那一层的目标（`RETRY` 决策需要知道重试什么）；
    `episode_trace` 是刚跑完那一局的**完整** trace（不是全量 run trace）——
    一次请求自带审查所需的全部依据，前端不用再额外请求一次、也不用自己
    维护跨会话的历史缓存（见 `docs/ROADMAP.md`“前后端交互统一”）。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话）")
    outcomes: list[HarnessEpisodeOutcomeResp] = Field(
        description="已完成的 episode 结算，按执行顺序；最后一条 = 刚跑完的",
    )
    goals: list[TaskForHarness] = Field(
        description="当前目标栈，栈顶 = goals[-1]（下一层要解决的）",
    )
    last_task: TaskForHarness | None = Field(
        default=None, description="刚跑完那一层的目标（RETRY 时压回栈顶用）"
    )
    episode_trace: list[TraceEvent] = Field(
        default_factory=list,
        description="刚跑完那一局的完整 trace（单 episode，不是全量 run trace）",
    )


class HumanReviewRespFromFrontend(BaseModel):
    """人类给的决策，`decision` 见 `HumanDecision`。

    加/改/删目标统一走 `POST /runs/{id}/goals`（`GoalsEdit`，整栈原子替换），
    与“这一轮 episode 怎么办”（continue/stop/retry）分开。
    """

    decision: HumanDecision = Field(description="人类对下一层的决策")
