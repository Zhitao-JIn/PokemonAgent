"""retrieval 的 reciprocal_rank_fusion：多路排名按 1/(k+rank) 融合（k 默认 60）。"""

from __future__ import annotations

import pytest

from pokemon_agent.memory.retrieval import RRF_K, reciprocal_rank_fusion


def test_rrf_sums_reciprocal_ranks_across_rankings() -> None:
    """同一下标在两路都排第一：分数 = 2/(60+1)（两路贡献相加）。"""

    # Arrange
    rankings = [[2, 0, 1], [2, 1, 0]]

    # Act
    scores = reciprocal_rank_fusion(rankings)

    # Assert
    assert scores[2] == pytest.approx(2 / (RRF_K + 1))


def test_rrf_omits_documents_absent_from_every_ranking() -> None:
    """返回 dict 的键只含至少在一路排名里出现过的下标（没出现的不列 0 分）。"""

    # Arrange
    rankings = [[0, 1]]

    # Act
    scores = reciprocal_rank_fusion(rankings)

    # Assert
    assert set(scores) == {0, 1}


def test_rrf_returns_empty_dict_for_no_rankings() -> None:
    """一路排名都没有：返回空 dict（不是报错）。"""

    # Arrange / Act
    scores = reciprocal_rank_fusion([])

    # Assert
    assert scores == {}


def test_rrf_uses_k_of_60_by_default() -> None:
    """默认 k=60：第一名的分数 = 1/61（平滑常数与文献经验值一致）。"""

    # Arrange
    rankings = [[0]]

    # Act
    scores = reciprocal_rank_fusion(rankings)

    # Assert
    assert scores[0] == pytest.approx(1 / 61)
