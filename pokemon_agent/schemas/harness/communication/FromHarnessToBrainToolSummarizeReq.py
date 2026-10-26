"""`FromHarnessToBrainToolSummarizeReq`：harness → `BrainTool` 的 episode 蒸馏请求。

**`entries` 装本局全部 TaskMemory**；正/负判断由蒸馏那次调用自己做（verify 已并入，
不再有单独的标注入参）。
`prompt` 不在这里：`BrainTool.summarize()` 入口处自己拼。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.termination import Settled, Termination
from pokemon_agent.schemas.memory import TaskMemory


class FromHarnessToBrainToolSummarizeReq(Settled, BaseModel):
    """harness 侧组装、交给 `BrainTool` 的 episode 蒸馏请求。"""

    entries: list[TaskMemory] = Field(
        min_length=1, description="本局全部 TaskMemory，按 total_acts 升序"
    )
    episode_id: str = Field(description="来源章")
    run_id: str = Field(description="来源章")
    run_goal: str = Field(description="所属 run 的目标文本，来源章")
    goal_id: str = Field(default="", description="来源章：本局所属 L1 goal 的 task_id")
    goal: str = Field(description="本局目标")
    termination: Termination = Field(description="终止类别（`success` 由它推出）")
    judge_reason: str = Field(
        default="", description="判停时的判定依据——蒸馏写结论时的参考，不必复述"
    )
    steps: int = Field(description="本局派了几个 task")
    acts_used: int = Field(default=0, description="本局累计按了几个键")
    max_steps: int = Field(description="本局 task 数预算")
