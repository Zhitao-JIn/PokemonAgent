"""retrieval 的 BM25 三段：建索引（build_bm25 / build_bm25_from_corpus）与打分排名。"""

from __future__ import annotations

import pytest

from pokemon_agent.memory.retrieval import bm25_rank, build_bm25, build_bm25_from_corpus


def test_build_bm25_rejects_empty_documents() -> None:
    """空文档列表建不了索引：入口断言拒绝。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        build_bm25([])


def test_build_bm25_from_corpus_rejects_empty_corpus() -> None:
    """空语料（已分好词的文档列表）同样建不了索引：入口断言拒绝。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        build_bm25_from_corpus([])


def test_bm25_rank_puts_document_sharing_query_bigrams_first() -> None:
    """三条文档里唯一与查询共享 bigram 的那条排第一。"""

    # Arrange
    query = "甲乙"
    documents = ["甲甲方", "丙丁戊", "戊己庚"]

    # Act
    ranking = bm25_rank(query, documents)

    # Assert
    assert ranking[0] == 0


def test_bm25_rank_returns_indices_covering_every_document() -> None:
    """返回下标集合 = range(len(documents))：无重复、无遗漏（排名是全排列）。"""

    # Arrange
    documents = ["甲乙丙", "丙丁戊", "戊己庚", "庚辛壬"]

    # Act
    ranking = bm25_rank("甲乙", documents)

    # Assert
    assert sorted(ranking) == list(range(len(documents)))


def test_bm25_rank_with_prebuilt_index_matches_fresh_build() -> None:
    """传入 prebuilt 索引与现建索引的打分结果完全相同（缓存不改语义，D4 输出等价）。"""

    # Arrange
    query = "甲乙"
    documents = ["甲甲方", "丙丁戊", "戊己庚"]
    prebuilt = build_bm25(documents)

    # Act
    with_prebuilt = bm25_rank(query, documents, prebuilt=prebuilt)
    fresh = bm25_rank(query, documents)

    # Assert
    assert with_prebuilt == fresh


def test_bm25_rank_rejects_empty_documents() -> None:
    """空文档列表无分可打：入口断言拒绝。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        bm25_rank("甲乙", [])
