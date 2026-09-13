"""`FromHarnessToBrainToolSummarizeResp`：`BrainTool` → harness 的蒸馏响应。

`episode_memory` 由 `BrainTool` 组装——大脑只吐 `EpisodeSummary`（它自己的
形状），tool 拿它 + harness 侧的元信息装配成存储形状。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import EpisodeSummary
from pokemon_agent.schemas.memory import EpisodeMemory

from .ModelCall import ModelCall


class FromHarnessToBrainToolSummarizeResp(BaseModel):
    """`BrainTool.summarize()` 交回给 harness 的结果。

    **拿不到结果时抛 `MaxRetriesExceeded`**（整条账在异常里）——旧契约的
    "`summary=None` 表示这次没蒸出东西"已废弃：那让"链路坏了"与"这一局确实
    没什么可总结"在数据里分不开。所以 `summary`/`episode_memory` 都是必有的。
    """

    summary: EpisodeSummary = Field(description="这次蒸馏出的跨局摘要")
    episode_memory: EpisodeMemory = Field(description="组装好的存储形状（尚未写库）")
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )
