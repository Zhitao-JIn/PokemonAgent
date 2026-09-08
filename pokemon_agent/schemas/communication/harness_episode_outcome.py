"""编排者给出的一局结算（`HarnessEpisodeOutcomeResp`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HarnessEpisodeOutcomeResp(BaseModel):
    """**编排者给出的一次任务尝试的最终结果**。

    **不携带 `task_id`**：那是实验层的分组键（任务库标识/统计聚合），
    实验层自己知道在跑哪个任务、自己维护统计——harness 只认任务本体
    （`goal`/`criteria`/`max_steps`）。MC 回填拿 `success` 作 episode
    的最终回报沿轨迹往回传。
    """

    episode_id: str = Field(description="本次尝试的标识")
    success: bool
    steps: int = Field(description="实际用了多少步")
    reason: str = Field(description="终止原因：success / failed / max_steps_exceeded / error")
