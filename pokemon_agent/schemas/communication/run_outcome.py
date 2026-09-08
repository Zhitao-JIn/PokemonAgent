"""编排者给出的一次 run 的结算（`RunOutcomeResp`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .harness_episode_outcome import HarnessEpisodeOutcomeResp


class RunOutcomeResp(BaseModel):
    """**一个 run（完整一局游戏）的最终结算**：run_id + 每个 episode 的结算 + 汇总。

    `outcomes` 是每个子 agent（episode）的结算，按执行顺序；`total`/`succeeded`/
    `success_rate` 是主 agent 自己算好的汇总——run 级是结算方，不把统计丢给调用方。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话）")
    outcomes: list[HarnessEpisodeOutcomeResp] = Field(
        default_factory=list, description="每个 episode 的结算，按执行顺序"
    )
    total: int = Field(ge=0, description="跑了多少个 episode")
    succeeded: int = Field(ge=0, description="其中成功几个")
    success_rate: float = Field(ge=0.0, le=1.0, description="成功率（0.0-1.0）")
