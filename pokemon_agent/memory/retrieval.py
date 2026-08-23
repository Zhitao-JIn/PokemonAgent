"""混合检索：BM25（关键词）+ embedding（向量）用 RRF 融合出候选集，
再用 reranker 精排出最终顺序和分数。**只依赖注入进来的 `EmbeddingProvider`/
`RerankerProvider`，不知道具体是 `fastembed` 还是别的什么**——理由同
`memory/util.py`：这一层是编排逻辑，不是存储，不该跟具体后端绑死。

## 为什么是"粗筛 + 精排"两段，不是直接精排全部候选

`RerankerProvider.rerank()` 是逐对计算的 cross-encoder，对每一对
`(query, document)` 都要跑一次推理——候选集一旦上百条，直接精排全部的延迟
和成本都不划算。所以先用两路便宜的排名（BM25 不需要模型、embedding 可以
批量算）粗筛出一小撮最有希望的候选（`fuse_top_k`），只对这一小撮跑精排。
这是标准 RAG 管线的形状，不是这个项目自己发明的取巧。

## 为什么粗筛是"两路 RRF 融合"，不是"BM25 or 向量选一个"

关键词检索（BM25）和向量检索（embedding 余弦）各有各的盲区：BM25 只认
字面重叠，同义改写、说法不同但意思一样的文本它找不到；向量检索能捕捉语义
相近，但短查询、专有名词（"招式"、"PP 值"这类游戏黑话）反而是 BM25 更可靠。
两路各自独立排名，用 Reciprocal Rank Fusion 合并——RRF 只看"排第几"不看
"分数具体是多少"，避免了 BM25 分数和余弦相似度**量纲完全不同**、
没法直接相加这个问题。
"""

from __future__ import annotations

import math

from rank_bm25 import BM25Okapi

from pokemon_agent.interfaces.embedding import EmbeddingProvider
from pokemon_agent.interfaces.rerank import RerankerProvider
from pokemon_agent.memory.vector import tokenize

RRF_K = 60
"""RRF 公式里的平滑常数，`1 / (k + rank)`——60 是文献（Cormack et al. 2009）
给出的经验值，对排名靠前几位的权重差异做了适度平滑，不需要针对这个项目调。
"""


def bm25_rank(query: str, documents: list[str]) -> list[int]:
    """BM25 关键词打分，返回按分数降序排列的文档下标（0-based，对应 `documents`）。

    分词复用 `memory/vector.py` 的字符 bigram `tokenize`——和 TF-IDF 那版
    共用同一套"什么算一个 token"的定义，不是巧合：两者都是"没有分词器时，
    字符 bigram 是中文短文本最省事的折中"这同一个理由。
    """
    assert documents, "bm25_rank() needs at least one document"
    corpus = [tokenize(doc) for doc in documents]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    return sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)


def embedding_rank(
    query: str,
    documents: list[str],
    embedder: EmbeddingProvider,
    document_vectors: list[list[float]] | None = None,
) -> list[int]:
    """向量余弦相似度打分，返回按相似度降序排列的文档下标。

    `document_vectors` 可选：候选文档的向量如果调用方已经算过（比如
    `MemoryTool` 在写入时就缓存了每条跨局摘要记忆/知识片段的向量），
    传进来就不用每次检索都重新 embed 一遍全部候选——只有 `query` 是
    每次检索都必须现算的（同一个 query 通常只用一次，缓存没意义）。
    不传的话（`None`）退回"每次都现算"，调用方图省事、候选集本来就很小时可以这样。

    前置条件：传了 `document_vectors` 时长度必须和 `documents` 一致。
    """
    assert documents, "embedding_rank() needs at least one document"
    query_vec = embedder.embed([query])[0]
    if document_vectors is not None:
        assert len(document_vectors) == len(documents), (
            "document_vectors must line up with documents"
        )
        doc_vecs = document_vectors
    else:
        doc_vecs = embedder.embed(documents)
    scores = [_cosine(query_vec, v) for v in doc_vecs]
    return sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """给多路排名（每路是一份下标列表，越靠前代表这一路认为越相关）做 RRF 融合。

    后置条件：返回的 dict 只包含**至少在一路排名里出现过**的下标——
        融合分数为 0 等价于"哪一路都没选中它"，不需要显式列出来。
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_retrieve(
    query: str,
    documents: list[str],
    embedder: EmbeddingProvider,
    reranker: RerankerProvider,
    fuse_top_k: int = 10,
    document_vectors: list[list[float]] | None = None,
) -> list[tuple[int, float]]:
    """完整两阶段检索：BM25 + 向量各自排名 → RRF 融合取前 `fuse_top_k` →
    reranker 对这一小撮精排出最终分数。

    返回 `(原始下标, reranker 分数)` 的列表，**按分数降序**，长度是
    `min(fuse_top_k, len(documents))`——原始下标是为了让调用方能把结果映回
    `documents` 之外的其他元数据（比如 `MemoryTool` 要把它映回 `EpisodeMemory`
    对象本身，不只是文本）；带着 reranker 分数一起返回，是为了让调用方能在
    这个分数之上再叠加别的排序信号（比如质量分、成败），不用重新计算一遍。

    前置条件：`documents` 非空。
    """
    assert documents, "hybrid_retrieve() needs at least one document"
    bm25_ranking = bm25_rank(query, documents)
    emb_ranking = embedding_rank(query, documents, embedder, document_vectors)
    fused = reciprocal_rank_fusion([bm25_ranking, emb_ranking])
    candidate_idx = sorted(fused, key=lambda i: fused[i], reverse=True)[:fuse_top_k]

    candidate_docs = [documents[i] for i in candidate_idx]
    rerank_scores = reranker.rerank(query, candidate_docs)

    paired = sorted(zip(candidate_idx, rerank_scores), key=lambda p: p[1], reverse=True)
    assert len(paired) <= fuse_top_k, "hybrid_retrieve must respect fuse_top_k"
    return paired
