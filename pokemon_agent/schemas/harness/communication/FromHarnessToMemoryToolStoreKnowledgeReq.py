"""`FromHarnessToMemoryToolStoreKnowledgeReq`：harness → `MemoryTool` 的知识写入请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import KnowledgeRecord


class FromHarnessToMemoryToolStoreKnowledgeReq(BaseModel):
    """**已经组装好的世界知识**：这一层只落盘、不调模型。

    records：一条知识一个记录。**空列表是合法输入**（这一局什么都没读到）——
        那一跳什么都不做，不是错误。
    """

    records: list[KnowledgeRecord] = Field(default_factory=list, description="组装好的知识记录")


__all__ = ["FromHarnessToMemoryToolStoreKnowledgeReq"]
