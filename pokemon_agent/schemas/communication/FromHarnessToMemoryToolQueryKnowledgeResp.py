"""`FromHarnessToMemoryToolQueryKnowledgeResp`：harness → `MemoryTool` 的知识检索响应。"""

from __future__ import annotations

from pydantic import BaseModel


class FromHarnessToMemoryToolQueryKnowledgeResp(BaseModel):
    """**记忆库给出的检索结果**：内容及其来源。"""

    contents: list[str]
    sources: list[str]
