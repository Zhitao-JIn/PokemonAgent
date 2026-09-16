"""Embedding 提供方接口。

原来放在顶层 `pokemon_agent/interfaces/providers/`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProviderPort(Protocol):
    """把一批文本变成向量。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """把 texts 逐条变成向量。

        texts：要编码的文本列表，每条非空。
        前置条件：texts 非空。
        后置条件：返回向量与 texts 等长、顺序一致；维度相同；不保证单位向量。
        失败：底层模型不可用时抛异常，不返回空列表或全零向量。
        """
        ...
