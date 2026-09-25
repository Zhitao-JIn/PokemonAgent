"""`FromHarnessToMemoryToolFetchResp`：按键取回的记录，只填请求那一族的字段。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, ObjectFactEvent, TaskMemory


class FromHarnessToMemoryToolFetchResp(BaseModel):
    """按请求里键的顺序排列；与对应查询读口返回的是同一种记录。"""

    acts: list[ActMemory] = Field(default_factory=list)
    tasks: list[TaskMemory] = Field(default_factory=list)
    episodes: list[EpisodeMemory] = Field(default_factory=list)
    objects: list[ObjectFactEvent] = Field(default_factory=list)
    knowledge_contents: list[str] = Field(default_factory=list)
    knowledge_sources: list[str] = Field(default_factory=list)
