"""store 的 filter / delete_many / count：等值过滤、交集语义与删除计数。"""

from __future__ import annotations

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def _store_with_three(tmp_path) -> LocalMemoryStore:
    """三条记录：两条同 source、其中一条还带 topic（供交集与单桶用例复用）。"""
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "a", "topic": "battle"}, {"n": 1})
    store.put({"source": "a", "topic": "dialog"}, {"n": 2})
    store.put({"source": "b"}, {"n": 3})
    return store


def test_filter_with_empty_conditions_returns_every_uuid(tmp_path) -> None:
    """空 conditions 不过滤，返回全部 uuid。"""

    # Arrange
    store = _store_with_three(tmp_path)

    # Act
    found = store.filter({})

    # Assert
    assert len(found) == 3


def test_filter_intersects_every_condition(tmp_path) -> None:
    """两个条件取交集：source=a 且 topic=battle 只剩一条。"""

    # Arrange
    store = _store_with_three(tmp_path)

    # Act
    found = store.filter({"source": "a", "topic": "battle"})

    # Assert
    assert len(found) == 1


def test_filter_returns_empty_when_one_condition_has_no_bucket(tmp_path) -> None:
    """任一条件查不到桶 → 空（不需要看别的条件）。"""

    # Arrange
    store = _store_with_three(tmp_path)

    # Act
    found = store.filter({"source": "a", "topic": "no-such-topic"})

    # Assert
    assert found == []


def test_filter_matches_values_by_equality_only(tmp_path) -> None:
    """只支持等值匹配：`"5"` 不匹配 `"6"`（大小比较不归这一层）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"step": "5"}, {"n": 1})

    # Act
    found = store.filter({"step": "6"})

    # Assert
    assert found == []


def test_delete_many_removes_records_and_returns_count(tmp_path) -> None:
    """delete_many 返回实际删除条数，未知 uuid 不计入。"""

    # Arrange
    store = _store_with_three(tmp_path)
    doomed = store.filter({"source": "b"})

    # Act
    deleted = store.delete_many([*doomed, "no-such-uuid"])

    # Assert
    assert deleted == 1
    assert store.count() == 2
    assert not (tmp_path / "step_memory" / f"{doomed[0]}.json").exists()


def test_count_tracks_put_and_delete(tmp_path) -> None:
    """count 跟着 put 涨、跟着 delete 落。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    assert store.count() == 0

    # Act
    first = store.put({"source": "a"}, {"n": 1})
    store.put({"source": "a"}, {"n": 2})
    after_puts = store.count()
    store.delete_many([first])
    after_delete = store.count()

    # Assert
    assert after_puts == 2
    assert after_delete == 1
