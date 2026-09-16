"""混合检索：BM25 + 向量各排一次，RRF 融合，再交叉编码器精排。

三段各补对方的短板：BM25 认得死词（技能名、地名），向量认得改写，
交叉编码器读得懂"这条到底答不答得上这个问题"但太贵，所以只对前几条跑。

**两路分数必须先各自归一化再融合。** BM25 的分无上界，向量余弦在 [-1,1]，
直接相加等于让 BM25 独裁。这里用 RRF（只看排名不看绝对分），
连归一化这一步都省了——两路分数的量纲从此不必对齐。

**只认字符串，不认任何记忆类型**——所以它住 `memory/` 根而不是某个 kind 包：
跨局摘要记忆（`MemoryTool.query_episode_summaries`）和知识库
（`MemoryTool.query_knowledge`）共用这一份检索逻辑。

纯函数，不碰库也不碰模型（向量和精排分数由调用方算好传进来），
所以可以脱离 provider 单测。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from pokemon_agent.memory import EmbeddingProviderPort, RerankerProviderPort


def tokenize(text: str) -> list[str]:
    """将中文文本切成字符 bigram，供 BM25 使用。"""
    chars = [char for char in text if not char.isspace()]
    if len(chars) < 2:
        return chars
    return [chars[index] + chars[index + 1] for index in range(len(chars) - 1)]


RRF_K = 60
"""RRF 公式里的平滑常数，`1 / (k + rank)`——60 是文献（Cormack et al. 2009）
给出的经验值，对排名靠前几位的权重差异做了适度平滑，不需要针对这个项目调。
"""


def bm25_rank(query: str, documents: list[str]) -> list[int]:
    """BM25 关键词打分，返回按分数降序排列的文档下标（0-based，对应 `documents`）。

    分词用本文件的字符 bigram `tokenize`——没有分词器时，字符 bigram 是
    中文短文本最省事的折中。

    用 BM25 给候选打分，返回降序的下标。
    """
    assert documents, "bm25_rank() needs at least one document"
    corpus = [tokenize(doc) for doc in documents]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    return sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)


def embedding_rank(
    query: str,
    documents: list[str],
    embedder: EmbeddingProviderPort,
    document_vectors: list[list[float]] | None = None,
) -> list[int]:
    """向量余弦相似度打分，返回按相似度降序排列的文档下标。

    `document_vectors` 可选：候选文档的向量如果调用方已经算过（比如
    `MemoryTool` 在写入时就缓存了每条跨局摘要记忆/知识片段的向量），
    传进来就不用每次检索都重新 embed 一遍全部候选——只有 `query` 是
    每次检索都必须现算的（同一个 query 通常只用一次，缓存没意义）。
    不传的话（`None`）退回"每次都现算"，调用方图省事、候选集本来就很小时可以这样。

    前置条件：传了 `document_vectors` 时长度必须和 `documents` 一致。

    用向量余弦给候选打分，返回降序的下标。
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
    """两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """给多路排名（每路是一份下标列表，越靠前代表这一路认为越相关）做 RRF 融合。

    后置条件：返回的 dict 只包含**至少在一路排名里出现过**的下标——
        融合分数为 0 等价于"哪一路都没选中它"，不需要显式列出来。

    把多路排名融合成一份，返回融合后的下标与分数。
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_retrieve(
    query: str,
    documents: list[str],
    embedder: EmbeddingProviderPort,
    reranker: RerankerProviderPort,
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

    关键词与向量各排一次、融合、再精排，返回前几条。
    """
    assert documents, "hybrid_retrieve() needs at least one document"
    bm25_ranking = bm25_rank(query, documents)
    emb_ranking = embedding_rank(query, documents, embedder, document_vectors)
    fused = reciprocal_rank_fusion([bm25_ranking, emb_ranking])
    candidate_idx = sorted(fused, key=lambda i: fused[i], reverse=True)[:fuse_top_k]

    candidate_docs = [documents[i] for i in candidate_idx]
    rerank_scores = reranker.rerank(query, candidate_docs)

    paired = sorted(
        zip(candidate_idx, rerank_scores, strict=True), key=lambda p: p[1], reverse=True
    )
    assert len(paired) <= fuse_top_k, "hybrid_retrieve must respect fuse_top_k"
    return paired
