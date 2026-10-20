"""`FromHarnessToBrainToolSummarizeTaskReq`：harness → `BrainTool` 的 task 蒸馏请求。

**`entries` 装本 task 区间的全部 ActMemory，`verdicts` 是与之等长的正/负标注**——
负样本不丢，和正样本一起作参考交给蒸馏（渲染时由 tool 层打标）。
`prompt` 不在这里：`TaskSummarizer.summarize_task()` 入口处自己拼。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.schemas.harness.domain.termination import Settled, Termination
from pokemon_agent.schemas.memory import ActMemory


class FromHarnessToBrainToolSummarizeTaskReq(Settled, BaseModel):
    """harness 侧组装、交给 `TaskSummarizer` 的 task 蒸馏请求。"""

    entries: list[ActMemory] = Field(
        min_length=1, description="本 task 区间的全部 ActMemory，按 step 升序"
    )
    verdicts: list[VerifyVerdict] = Field(description="与 entries 等长的正/负标注")
    task_id: str = Field(description="本 task 的标识（来源章）")
    episode_id: str = Field(description="所属 episode 的标识（来源章）")
    run_id: str = Field(description="所属 run 的标识（来源章）")
    goal: str = Field(description="本 task 的目标")
    termination: Termination = Field(description="终止类别（`success` 由它推出）")
    judge_reason: str = Field(
        default="", description="判停时的判定依据——蒸馏写结论时的参考，不必复述"
    )
    steps_used: int = Field(description="本 task 消耗的键数")
    max_steps: int = Field(description="本 task 的键预算")
