"""`FromHarnessToBrainToolSummarizeReq`：harness → `BrainTool` 的 episode 蒸馏请求。

**`entries` 装本局全部 TaskMemory，`verdicts` 是与之等长的正/负标注**——
负样本不丢，和正样本一起作参考交给蒸馏（渲染时由 tool 层打标）。
`prompt` 不在这里：`BrainTool.summarize()` 入口处自己拼。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.schemas.harness.domain.termination import Settled, Termination
from pokemon_agent.schemas.memory import TaskMemory


class FromHarnessToBrainToolSummarizeReq(Settled, BaseModel):
    """harness 侧组装、交给 `BrainTool` 的 episode 蒸馏请求。"""

    entries: list[TaskMemory] = Field(
        min_length=1, description="本局全部 TaskMemory，按 start_step 升序"
    )
    verdicts: list[VerifyVerdict] = Field(description="与 entries 等长的正/负标注")
    episode_id: str = Field(description="来源章")
    run_id: str = Field(description="来源章")
    goal: str = Field(description="本局目标")
    termination: Termination = Field(description="终止类别（`success` 由它推出）")
    judge_reason: str = Field(
        default="", description="判停时的判定依据——蒸馏写结论时的参考，不必复述"
    )
    steps: int = Field(description="本局派了几个 task")
    acts_used: int = Field(default=0, description="本局累计按了几个键")
    max_steps: int = Field(description="本局 task 数预算")
