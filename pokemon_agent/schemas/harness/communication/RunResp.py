"""`RunResp`：RunHarness 对外的 run 接口模型——一次 run 的结算。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.episode_io import EpisodeOutput
from pokemon_agent.schemas.harness.domain.termination import Settled, Termination


class RunResp(Settled, BaseModel):
    """**一个 run（完整一局游戏）的最终结算**：run_id + 每个 episode 的结算 + 汇总。

    `outcomes` 是每个子 agent（episode）的结算，按执行顺序；`total`/`succeeded`/
    `success_rate` 是主 agent 自己算好的汇总——run 级是结算方，不把统计丢给调用方。

    **裸名、归 harness**：这五个字段全是 RunHarness 自己数出来的，跟谁发起这次 run
    无关（api 调、experiment 调都是它）。挂 `FromFrontendTo` 前缀会让一个纯后端产物
    跟着前端那条边归档，记账层想内嵌它就得反过来 import 前端包。
    """

    run_id: str = Field(description="这次 run 的标识（完整一局游戏会话）")
    outcomes: list[EpisodeOutput] = Field(
        default_factory=list, description="每个 episode 的结算，按执行顺序"
    )
    total: int = Field(ge=0, description="跑了多少个 episode")
    succeeded: int = Field(ge=0, description="其中成功几个")
    success_rate: float = Field(ge=0.0, le=1.0, description="成功率（0.0-1.0）")
    termination: Termination = Field(description="run 的终止类别（`success` 由它推出）")
    judge_reason: str = Field(default="", description="run 判停时的判定依据（review_and_judge 写）")
