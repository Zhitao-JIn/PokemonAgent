"""`FromHarnessToBrainToolExtractResp`：`BrainTool` → harness 的世界知识抽取响应。

**`records` 已经是存储形状**（`KnowledgeRecord`），不是脑子的方言——组装发生在
`BrainTool.extract()`：来源字段（`source`/`run_id`/`episode_id`）只有它两边都认识，
大脑不知道自己在哪一局（同 `summarize()` 组装 `EpisodeMemory` 的分工）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import KnowledgeRecord

from .ModelCall import ModelCall


class FromHarnessToBrainToolExtractResp(BaseModel):
    """`BrainTool.extract()` 交回给 harness 的结果。

    records：这一局读到的世界知识，**可以是空列表**——什么都没读到是常态，
        不是失败。空列表与"抽取失败"必须分得开：后者抛
        `MaxRetriesExceeded`（整条账在异常里）。
    calls：整条重试链的账，按尝试顺序，最后一个是成功那次。
    """

    records: list[KnowledgeRecord] = Field(
        default_factory=list, description="组装好的知识记录（尚未写库；可以一条都没有）"
    )
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )


__all__ = ["FromHarnessToBrainToolExtractResp"]
