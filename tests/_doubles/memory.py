"""memory 测试共用的检索替身：确定性 embedder 与重叠度 reranker。

两个替身都只依赖字符串形状、不调模型：`DeterministicEmbedder` 把 bigram 哈希进
固定 16 维（同一文本永远得同一向量，测试可复现），`OverlapReranker` 以「query 与
文档共有 bigram 数」打分——足够断言"谁排第一"，不依赖排序质量（那是评测的事，
spec D2）。零向量 embedder 不进这里（spec D3：零向量语义在 retrieval 测试文件内
手写单独钉）。
"""

from __future__ import annotations

import hashlib

from pokemon_agent.memory.retrieval import tokenize

DIM = 16
"""确定性 embedder 的向量维度（固定小维度：断言可读，矩阵乘也快）。"""


class DeterministicEmbedder:
    """确定性 embedder：`embed(texts)` 按 bigram 哈希进 16 维。

    `calls` 累计**收到的文本条数**——`embedding_rank` 省不省那次全候选 embed，
    只有通过它才观测得到（向量内容对调用方不可见，这正是契约）。
    """

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [_hash_bigrams(text) for text in texts]


class OverlapReranker:
    """reranker 替身：分数 = query 与文档共有的 bigram 数（0 也合法）。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        assert documents, "rerank() needs at least one document"
        query_bigrams = set(tokenize(query))
        return [float(len(query_bigrams & set(tokenize(doc)))) for doc in documents]


def _hash_bigrams(text: str) -> list[float]:
    """把文本的 bigram 哈希进 16 维：每个 bigram 给命中维 +1（sha256 保证跨进程一致）。"""
    vector = [0.0] * DIM
    for bigram in tokenize(text):
        index = hashlib.sha256(bigram.encode("utf-8")).digest()[0] % DIM
        vector[index] += 1.0
    return vector
