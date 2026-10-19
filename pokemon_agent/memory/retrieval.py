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

import time
from typing import TYPE_CHECKING

import numpy as np
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from pokemon_agent.memory import EmbeddingProviderPort, RerankerProviderPort

Timings = dict[str, float]
"""检索分段耗时：段名 → 秒。**和结果一起从返回值出来**（0928 324）——对齐
模型 provider 的先例：`complete()` 的返回除了正文还带 token 用量，检索的返回
除了命中还带各段耗时。观测数据是产出的一部分，不是旁路回调，也不该逼调用方
另开收集通道。段位见 `hybrid_retrieve` 的 docstring。

**向量打分是 numpy 扁平精确索引**（0928 327）：全部候选向量组装成一个矩阵，
一次矩阵乘法算完所有余弦——这是 ANN 索引家族里的 `IndexFlat`（精确检索）形态，
十万条毫秒级。将来数据量真到了要 HNSW/IVF 的量级，只换这一处实现，接口不变；
在那之前上近似索引是纯负担（建索引比查询还贵）。"""


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


def build_bm25(documents: list[str]) -> BM25Okapi:
    """对候选集**建一次** BM25 索引（`bm25_rank` 的构建半段，0928 326 拆出）。

    拆出来是为了让调用方能缓存复用：语料没变就不用每次查询重新分词全库。
    """
    assert documents, "build_bm25() needs at least one document"
    return BM25Okapi([tokenize(doc) for doc in documents])


def build_bm25_from_corpus(corpus: list[list[str]]) -> BM25Okapi:
    """从**已分好词**的语料建 BM25 索引——调用方持久化了 corpus（token 列表）
    时走这条，连全库分词都省掉（0928 326）。"""
    assert corpus, "build_bm25_from_corpus() needs at least one document"
    return BM25Okapi(corpus)


def bm25_rank(query: str, documents: list[str], prebuilt: BM25Okapi | None = None) -> list[int]:
    """BM25 关键词打分，返回按分数降序排列的文档下标（0-based，对应 `documents`）。

    分词用本文件的字符 bigram `tokenize`——没有分词器时，字符 bigram 是
    中文短文本最省事的折中。`prebuilt` 可选：调用方缓存了语料索引就传进来，
    跳过重建（0928 326）；查询词本身每次现 tokenize（同一个 query 通常只用一次）。

    用 BM25 给候选打分，返回降序的下标。
    """
    assert documents, "bm25_rank() needs at least one document"
    bm25 = prebuilt if prebuilt is not None else build_bm25(documents)
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

    向量余弦**一次矩阵乘算完全部候选**（0928 327 numpy 化）：逐条双循环在
    纯 Python 里是 O(N×维度) 的解释器开销，矩阵化后同一算法交给 BLAS——
    零向量（norm = 0）得 0 分，与旧 `_cosine` 的边界行为一致。
    """
    assert documents, "embedding_rank() needs at least one document"
    query_vec = np.asarray(embedder.embed([query])[0], dtype=np.float32)
    if document_vectors is not None:
        assert len(document_vectors) == len(documents), (
            "document_vectors must line up with documents"
        )
        doc_matrix = np.asarray(document_vectors, dtype=np.float32)
    else:
        doc_matrix = np.asarray(embedder.embed(documents), dtype=np.float32)

    norms = np.linalg.norm(doc_matrix, axis=1) * np.linalg.norm(query_vec)
    dots = doc_matrix @ query_vec
    scores = np.divide(dots, norms, out=np.zeros_like(dots), where=norms > 0.0)
    order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
    return order


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
    prebuilt_bm25: BM25Okapi | None = None,
) -> tuple[list[tuple[int, float]], Timings]:
    """完整两阶段检索：BM25 + 向量各自排名 → RRF 融合取前 `fuse_top_k` →
    reranker 对这一小撮精排出最终分数。

    返回 `(结果, timings)` 二元组：

    - **结果**是 `(原始下标, reranker 分数)` 的列表，**按分数降序**，长度是
      `min(fuse_top_k, len(documents))`——原始下标是为了让调用方能把结果映回
      `documents` 之外的其他元数据（比如 `MemoryTool` 要把它映回 `EpisodeMemory`
      对象本身，不只是文本）；带着 reranker 分数一起返回，是为了让调用方能在
      这个分数之上再叠加别的排序信号（比如质量分、成败），不用重新计算一遍。
    - **timings** 是各段耗时（段名 → 秒）：`bm25` / `vector`（query embed + 余弦
      打分）/ `rrf` / `rerank`。对齐模型 provider"返回带 usage"的先例——耗时
      是这次检索的产出之一，从返回值出来，不进签名也不搞旁路。
      归因背景：0928 检索延迟剖析——2~9s 的主嫌疑是 rerank 段，等这里的账来证实。

    `prebuilt_bm25` 可选：调用方缓存了语料索引就传进来，`bm25` 段只做打分
    不重建（0928 326）。

    前置条件：`documents` 非空。

    关键词与向量各排一次、融合、再精排，返回前几条。
    """
    assert documents, "hybrid_retrieve() needs at least one document"
    timings: Timings = {}
    t0 = time.perf_counter()
    bm25_ranking = bm25_rank(query, documents, prebuilt=prebuilt_bm25)
    timings["bm25"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    emb_ranking = embedding_rank(query, documents, embedder, document_vectors)
    timings["vector"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    fused = reciprocal_rank_fusion([bm25_ranking, emb_ranking])
    timings["rrf"] = time.perf_counter() - t0

    candidate_idx = sorted(fused, key=lambda i: fused[i], reverse=True)[:fuse_top_k]

    candidate_docs = [documents[i] for i in candidate_idx]
    t0 = time.perf_counter()
    rerank_scores = reranker.rerank(query, candidate_docs)
    timings["rerank"] = time.perf_counter() - t0

    paired = sorted(
        zip(candidate_idx, rerank_scores, strict=True), key=lambda p: p[1], reverse=True
    )
    assert len(paired) <= fuse_top_k, "hybrid_retrieve must respect fuse_top_k"
    return paired, timings
