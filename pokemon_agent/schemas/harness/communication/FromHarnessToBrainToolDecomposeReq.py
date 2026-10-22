"""episode 级拆解的请求信封（harness → BrainTool 第一跳）。

只装素材：`BrainTool.decompose()` 自己拼 prompt、渲染素材行，再交给大脑。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.harness.domain.judge_feedback import JudgeFeedback
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, TaskMemory
from pokemon_agent.world import TaskObservation


class FromHarnessToBrainToolDecomposeReq(BaseModel):
    """拆一版任务链要的全部素材。"""

    remaining_planning_rounds: int | None = None
    execution_order: list[str] = Field(default_factory=list)
    goal: Goal = Field(description="本局目标（含判据）")
    observation: TaskObservation = Field(description="当前帧")
    task_memories: list[TaskMemory] = Field(
        default_factory=list, description="本局已跑 task 的记忆，按执行序"
    )
    task_table: list[TaskEntry] = Field(
        default_factory=list,
        description="本局任务表：已定案的成败（以表为准，含人审推翻）、被放弃的条目与版次",
    )
    episode_index: list[EpisodeMemory] = Field(
        default_factory=list,
        description="本 run 内同一个 L1 goal 的其他 episode，不含本局；只用 index_line 渲染",
    )
    knowledge: list[str] = Field(
        default_factory=list, description="episode 层检索到的领域知识全文，一篇一条（不筛）"
    )
    last_judge: JudgeFeedback | None = Field(
        default=None, description="本局上一次判定及人的表态；还没判过为 None"
    )
    max_tasks: int = Field(gt=0, description="这一版最多几个 task（给模型的建议上限）")
    human_note: str = Field(default="", description="人对上一版拆解的插话；空 = 没被插话")

    known_objects: list[ObjectFactEvent] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """历史请求未提供原始事件时保留原信封形状。"""
        data = handler(self)
        if "known_objects" not in self.model_fields_set:
            data.pop("known_objects", None)
        return data
