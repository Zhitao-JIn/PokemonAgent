"""`BrainTool` → `Brain` 这一跳的校验+蒸馏响应协议：
`VerifyAndSummarizeResp`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import EpisodeSummary, StepVerifyVerdict
from pokemon_agent.providers.interface import ModelCall
from pokemon_agent.schemas.memory import EpisodeMemory


class VerifyAndSummarizeResp(BaseModel):
    """**合并调用的结论**，连同它花了什么。

    verdicts 与 req.entries **等长**（同原 `StepVerifyResp` 的保证）；
    summary 是蒸馏出的摘要，**解析失败/调用失败时为 `None`**——调用方
    （`EpisodeHarness.verify_and_summarize`）据此决定这一局这次要不要落一条
    跨局摘要（`None` 就只记一条错误，不写摘要，等价于原 `summarize()` 遇到
    `ParseFailure` 时的处理）。`verdicts` 即使 `summary` 为 `None` 也仍然是
    "全部标不可靠"的保守兜底，而不是空列表——两者语义不同，跟原实现一致。
    """

    verdicts: list[StepVerifyVerdict] = Field(description="与 entries 等长的判定列表")
    summary: EpisodeSummary | None = Field(
        default=None, description="蒸馏出的摘要；调用/解析失败时为 None"
    )
    episode_memory: EpisodeMemory | None = Field(
        default=None,
        description="组装好的跨局摘要记忆（summary 非 None 时才有）——组装在 brain "
        "完成（ROADMAP 16），调用方拿到后直接落库，不再自己搬运字段。"
        "summary 为 None 时它也是 None",
    )
    call: ModelCall = Field(
        default_factory=ModelCall,
        description="这次合并调用的账。仍记在 Source.VERIFY 下（校验器自己的"
        "失效率报表沿用旧口径）——代价是这条账单现在也包含了写摘要那部分的"
        "token，不再是纯校验成本，见模块文档",
    )
    why: str = Field(default="", description="整体说明；失败时是失败信息")
