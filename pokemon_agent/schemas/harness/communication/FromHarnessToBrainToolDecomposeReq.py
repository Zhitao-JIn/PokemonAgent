"""episode 级拆解的请求信封（harness → BrainTool 第一跳）。

只装素材：`BrainTool.decompose()` 自己拼 prompt、渲染素材行，再交给大脑。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.memory import EpisodeMemory, TaskMemory
from pokemon_agent.world import Observation


class FromHarnessToBrainToolDecomposeReq(BaseModel):
    """拆一版任务链要的全部素材。"""

    goal: Goal = Field(description="本局目标（含判据）")
    observation: Observation = Field(description="当前帧")
    task_memories: list[TaskMemory] = Field(
        default_factory=list, description="本局已跑 task 的记忆，按执行序"
    )
    task_table: list[TaskEntry] = Field(
        default_factory=list,
        description="本局任务表：已定案的成败（以表为准，含人审推翻）、被放弃的条目与版次",
    )
    episode_memories: list[EpisodeMemory] = Field(
        default_factory=list, description="本 run 的跨局摘要"
    )
    max_tasks: int = Field(gt=0, description="这一版最多几个 task（给模型的建议上限）")
    human_note: str = Field(default="", description="人对上一版拆解的插话；空 = 没被插话")
