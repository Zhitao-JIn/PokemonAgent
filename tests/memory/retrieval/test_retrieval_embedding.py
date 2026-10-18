"""retrieval 的 embedding_rank：向量余弦相似度打分（含零向量边界与 embed 时机）。"""

from __future__ import annotations

import pytest
from _doubles.memory import DIM, DeterministicEmbedder

from pokemon_agent.memory.retrieval import embedding_rank

_QUERY = "甲乙丙"


class _ZeroVectorDocEmbedder:
    """对标记文本返回零向量的手写替身（D3：零向量语义不进共用替身）。

    其余文本走 `DeterministicEmbedder`——这样 query 与正常候选仍是可比的非零向量，
    只有被标记的那条候选 norm=0，正好钉住"零向量得 0 分"的边界。
    """

    def __init__(self) -> None:
        self._inner = DeterministicEmbedder()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vectors.append([0.0] * DIM if text == "ZERO" else self._inner.embed([text])[0])
        return vectors


def test_embedding_rank_orders_documents_by_cosine_similarity() -> None:
    """与 query 向量夹角最小的文档排第一（共享 bigram 的候选赢零重叠的）。"""

    # Arrange
    documents = ["甲乙丙丁", "戊己庚辛"]

    # Act
    ranking = embedding_rank(_QUERY, documents, DeterministicEmbedder())

    # Assert
    assert ranking[0] == 0


def test_embedding_rank_scores_zero_vector_document_as_zero() -> None:
    """零向量候选（norm=0）得 0 分，排在正相似度候选之后。"""

    # Arrange
    documents = ["甲乙丙", "ZERO"]

    # Act
    ranking = embedding_rank(_QUERY, documents, _ZeroVectorDocEmbedder())

    # Assert
    assert ranking[0] == 0
    assert ranking[-1] == 1


def test_embedding_rank_embeds_documents_only_when_vectors_not_supplied() -> None:
    """传入 document_vectors 时 embedder 只收到 query（计数 = 1，候选不重算）。"""

    # Arrange
    embedder = DeterministicEmbedder()
    document_vectors = [[1.0] * DIM, [0.5] * DIM]

    # Act
    embedding_rank(_QUERY, ["a", "b"], embedder, document_vectors=document_vectors)

    # Assert
    assert embedder.calls == 1


def test_embedding_rank_embeds_query_and_documents_when_vectors_not_supplied() -> None:
    """不传 document_vectors 时 embedder 收到 query + 全部候选（计数 = 1 + 文档数）。"""

    # Arrange
    embedder = DeterministicEmbedder()
    documents = ["甲乙丙", "丙丁戊", "戊己庚"]

    # Act
    embedding_rank(_QUERY, documents, embedder)

    # Assert
    assert embedder.calls == 1 + len(documents)


def test_embedding_rank_rejects_mismatched_document_vectors() -> None:
    """document_vectors 与 documents 长度不等：前置断言拒绝（对不上就是调用方 bug）。"""

    # Arrange
    document_vectors = [[1.0] * DIM]

    # Act / Assert
    with pytest.raises(AssertionError):
        embedding_rank(
            _QUERY, ["a", "b"], DeterministicEmbedder(), document_vectors=document_vectors
        )


def test_embedding_rank_rejects_empty_documents() -> None:
    """空文档列表无分可打：入口断言拒绝。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        embedding_rank(_QUERY, [], DeterministicEmbedder())
