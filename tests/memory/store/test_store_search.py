"""store 的 search / rank：limit 前置断言、空 text 候选、截断与 rank 入口断言。"""

from __future__ import annotations

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def test_search_rejects_non_positive_limit(tmp_path) -> None:
    """CP3 回归：limit<=0 在入口就断言拒绝，不再按切片语义静默返回。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    for i in range(3):
        store.put({"source": "s"}, {"n": i}, text=f"宝可梦 正文 {i}")

    # Act / Assert
    with pytest.raises(AssertionError):
        store.search("宝可梦", limit=-1)
    with pytest.raises(AssertionError):
        store.search("宝可梦", limit=0)
    uuids, _timings = store.search("宝可梦", limit=1)

    # Assert
    assert len(uuids) == 1


def test_search_excludes_candidates_with_empty_text(tmp_path) -> None:
    """无 text 的记录不进语义检索（搜不到它）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "with-text"}, {"n": 1}, text="宝可梦 正文")
    store.put({"source": "no-text"}, {"n": 2})

    # Act
    hits, _timings = store.search("宝可梦", limit=5)

    # Assert
    assert hits == store.filter({"source": "with-text"})


def test_search_returns_empty_when_no_candidates(tmp_path) -> None:
    """conditions 无匹配 → 空列表（不是报错）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "a"}, {"n": 1}, text="正文")

    # Act
    hits, _timings = store.search("正文", limit=5, conditions={"source": "no-such-source"})

    # Assert
    assert hits == []


def test_search_returns_at_most_limit_results(tmp_path) -> None:
    """结果条数不超过 limit（候选多于 limit 时截断）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    for i in range(5):
        store.put({"source": "s"}, {"n": i}, text=f"宝可梦 正文 {i}")

    # Act
    hits, _timings = store.search("宝可梦", limit=2)

    # Assert
    assert len(hits) == 2


def test_rank_rejects_empty_query(tmp_path) -> None:
    """空 query 在 rank 入口即被断言拒绝。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        store.rank([], "", fuse_top_k=10)


def test_rank_rejects_non_positive_fuse_top_k(tmp_path) -> None:
    """fuse_top_k<=0 在 rank 入口即被断言拒绝。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        store.rank([], "正文", fuse_top_k=0)
