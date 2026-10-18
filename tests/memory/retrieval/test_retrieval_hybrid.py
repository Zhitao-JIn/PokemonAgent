"""retrieval 的 hybrid_retrieve：BM25 + 向量 → RRF → reranker 的两阶段检索入口。"""

from __future__ import annotations

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory.retrieval import build_bm25, hybrid_retrieve

_QUERY = "甲乙丙"
_DOCUMENTS = ["甲乙丙丁", "丙丁戊己", "戊己庚辛", "甲乙戊己", "庚辛壬癸"]


class _RecordingReranker:
    """把每次收到的候选文档记下来的 OverlapReranker 包装（只为观测喂了什么）。"""

    def __init__(self) -> None:
        self._inner = OverlapReranker()
        self.seen: list[list[str]] = []

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.seen.append(list(documents))
        return self._inner.rerank(query, documents)


def test_hybrid_returns_fuse_top_k_results_sorted_by_rerank_score() -> None:
    """结果长度 = min(fuse_top_k, n)，且按 reranker 分数降序。"""

    # Arrange / Act
    results, _timings = hybrid_retrieve(
        _QUERY, _DOCUMENTS, DeterministicEmbedder(), OverlapReranker(), fuse_top_k=3
    )

    # Assert
    assert len(results) == 3
    scores = [score for _index, score in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_returns_all_documents_when_fuse_top_k_exceeds_count() -> None:
    """fuse_top_k 大于文档数时：结果长度 = 文档数（不补齐、不报错）。"""

    # Arrange / Act
    results, _timings = hybrid_retrieve(
        _QUERY, _DOCUMENTS, DeterministicEmbedder(), OverlapReranker(), fuse_top_k=100
    )

    # Assert
    assert len(results) == len(_DOCUMENTS)


def test_hybrid_reports_four_timing_stages() -> None:
    """timings 的键恰为 bm25 / vector / rrf / rerank 四段，值都是非负浮点。"""

    # Arrange / Act
    _results, timings = hybrid_retrieve(
        _QUERY, _DOCUMENTS, DeterministicEmbedder(), OverlapReranker()
    )

    # Assert
    assert set(timings) == {"bm25", "vector", "rrf", "rerank"}
    assert all(isinstance(seconds, float) and seconds >= 0.0 for seconds in timings.values())


def test_hybrid_feeds_reranker_only_the_fused_candidates() -> None:
    """reranker 只收到 RRF 融合后的前 fuse_top_k 个候选（不是全库）。"""

    # Arrange
    reranker = _RecordingReranker()

    # Act
    hybrid_retrieve(_QUERY, _DOCUMENTS, DeterministicEmbedder(), reranker, fuse_top_k=2)

    # Assert
    assert len(reranker.seen) == 1
    assert len(reranker.seen[0]) == 2


def test_hybrid_with_prebuilt_bm25_matches_fresh_build() -> None:
    """传入 prebuilt_bm25 与现建索引的最终结果相同（D4：只测输出等价）。"""

    # Arrange
    prebuilt = build_bm25(_DOCUMENTS)

    # Act
    with_prebuilt, _ = hybrid_retrieve(
        _QUERY, _DOCUMENTS, DeterministicEmbedder(), OverlapReranker(), prebuilt_bm25=prebuilt
    )
    fresh, _ = hybrid_retrieve(_QUERY, _DOCUMENTS, DeterministicEmbedder(), OverlapReranker())

    # Assert
    assert with_prebuilt == fresh


def test_hybrid_rejects_empty_documents() -> None:
    """空文档列表没有可检索的候选：入口断言拒绝。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        hybrid_retrieve(_QUERY, [], DeterministicEmbedder(), OverlapReranker())
