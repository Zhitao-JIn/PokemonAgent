"""Reranker 提供方接口。

和 `interfaces/embedding.py` 分开成两个 Protocol，不合并成一个"检索模型"接口：
embedding 和 reranker 是**两种不同的模型、答不同的问题**——embedding 把文本
独立映射成向量（可以离线批量算好、缓存、只对新文本增量算），reranker 对
`(query, document)` 这一个具体的组合打分（必须每次查询现算，没法脱离 query
单独缓存 document 的分）。合并成一个接口只会让"这个方法能不能被缓存"变成
要靠文档说明的隐藏知识，拆开之后类型签名本身就说明了这一点。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RerankerProvider(Protocol):
    """给一个 query 和一批候选文档打相关性分。

    只用来对**已经缩小过的候选集**做精排——见 `memory/retrieval.py` 里
    "先用关键词+向量粗筛出一小撮候选，再用 reranker 精排"这个两阶段设计。
    reranker 是逐对计算的，直接对全库跑一遍代价太高，这一层的调用方有责任
    只把粗筛后的候选集传进来，不是整座库。
    """

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """给 `documents` 里每一条相对 `query` 的相关性打分，返回值与
        `documents` 等长、顺序一致（不是按分数排过序的——排序是调用方的事，
        这一层只管打分，理由同 `LLMProvider`：拆开职责，方便单独测试）。

        前置条件：`query` 非空；`documents` 非空，且每条非空。
        后置条件：分数值域由具体实现决定（不同 reranker 模型的分数范围不同，
            这一层不强行统一成 [0, 1]——统一了反而会掩盖"这个模型的分数
            本来就没有一个自然的上下界"这件事，调用方如果要归一化，
            自己按拿到的这一批分数的 min/max 做，不该由这一层替它决定）。
        失败：底层模型不可用时抛异常，不返回全零分数列表——理由同
            `EmbeddingProvider.embed`。

        给每条候选打一个相对查询的相关性分，顺序与输入一致。
        """
        ...
