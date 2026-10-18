"""store 的索引自愈：index.json 是派生物，缺失或与文件集合不符时按记录文件重建。"""

from __future__ import annotations

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def test_missing_index_file_is_rebuilt_from_record_files(tmp_path) -> None:
    """删掉 index.json 后，新实例仍能 filter 到记录（真相是记录文件）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "a"}, {"n": 1})
    (tmp_path / "step_memory" / "index.json").unlink()

    # Act
    fresh = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Assert
    assert fresh.count() == 1
    assert fresh.filter({"source": "a"})


def test_hand_removed_record_is_reconciled_on_startup(tmp_path) -> None:
    """手工删掉记录文件后，新实例的 count 与 filter 都反映删除。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    doomed = store.put({"source": "gone"}, {"n": 1})
    store.put({"source": "kept"}, {"n": 2})
    (tmp_path / "step_memory" / f"{doomed}.json").unlink()

    # Act
    fresh = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Assert
    assert fresh.count() == 1
    assert not fresh.filter({"source": "gone"})
    assert fresh.filter({"source": "kept"})
