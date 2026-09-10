"""`FromHarnessToMemoryToolQueryEpisodeSummariesReq`：harness → `MemoryTool` 的跨局摘要检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryEpisodeSummariesReq(BaseModel):
    """**按场景检索跨局摘要**。

    run_id 空串 = 不限 run，仅测试用：跨 run 的经验对当前 run 是别人家的答案。
    """

    scene: str = Field(description="当前场景，非空")
    query: str = Field(description="检索文本，非空")
    limit: int = Field(default=3, gt=0, description="条数上限")
    run_id: str = Field(default="", description="只检索这一个 run 沉淀的摘要；空串 = 不限")
