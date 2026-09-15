"""`FromHarnessToMemoryToolStoreKnowledgeResp`：harness → `MemoryTool` 的知识写入响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import KnowledgeRecord


class FromHarnessToMemoryToolStoreKnowledgeResp(BaseModel):
    """**真的落库了的那几条**（检索索引已同步更新）。

    比 `req.records` 少是正常的：**判重在写口做**——同 `topic` 且正文逐字相同的
    条目会被跳过（同一件事被两局分别学到时，别在库里堆第二份）。
    返回实际写入的那些，让调用方**能从返回值看出"我给的被吃掉了没有"**，
    而不是自己去猜为什么库里条数没涨。
    """

    stored: list[KnowledgeRecord] = Field(
        default_factory=list, description="实际落库的记录（判重后剩下的）"
    )


__all__ = ["FromHarnessToMemoryToolStoreKnowledgeResp"]
