"""`FromHarnessToMemoryToolQueryKnowledgeReq`：harness → `MemoryTool` 的知识检索请求。"""

from __future__ import annotations

from pydantic import BaseModel


class FromHarnessToMemoryToolQueryKnowledgeReq(BaseModel):
    """**递给记忆库的知识检索请求**。

    query：检索文本。
    limit：条数上限。
    """

    query: str
    limit: int = 5
