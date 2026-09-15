"""`FromHarnessToMemoryToolQueryEpisodeSummariesResp`：
harness → `MemoryTool` 的跨局摘要读取响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import EpisodeMemory


class FromHarnessToMemoryToolQueryEpisodeSummariesResp(BaseModel):
    """**命中过滤条件的跨局摘要**——全量返回，不排序、不截断（0914 定案）。

    顺序只保证"同一个库读两次一样"（按 `episode_id` 字典序），**不含相关性含义**；
    要按相关性/质量/成败重排或裁掉几条，是消费方自己的事。
    """

    summaries: list[EpisodeMemory] = Field(
        description="命中的跨局摘要（全量，按 episode_id 落定顺序）"
    )
