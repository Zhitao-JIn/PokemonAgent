"""Reranker 提供方接口。

原来放在顶层 `pokemon_agent/interfaces/providers/`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RerankerProvider(Protocol):
    """给一个 query 和一批候选文档打相关性分。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """给 documents 里每条相对 query 打相关性分。

        query：查询文本，非空。
        documents：候选文档列表，非空、每条非空。
        前置条件：query 非空、documents 非空。
        后置条件：返回分数与 documents 等长、顺序一致，未排序。
        失败：底层模型不可用时抛异常，不返回全零分数。
        """
        ...
