"""store 的 snapshot / restore：整根打包、同名覆盖、路径分隔符拒绝与以 zip 为准的还原。"""

from __future__ import annotations

import zipfile

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def test_snapshot_writes_zip_containing_the_kind_records(tmp_path) -> None:
    """快照打的是整个记忆根，落在 `<根>/snapshots/<name>.zip`，且里面没有 `snapshots/`。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "a"}, {"n": 1})

    # Act
    archive = store.snapshot("s1")

    # Assert
    assert archive == tmp_path / "snapshots" / "s1.zip"
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert any(name.startswith("step_memory/") for name in names), names
    assert not any(name.startswith("snapshots/") for name in names), names


def test_snapshot_overwrites_a_previous_one_with_the_same_name(tmp_path) -> None:
    """同名快照覆盖——`name` 是调用方给的标识，不是一个自增号。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    first = store.snapshot("s1")
    first_size = first.stat().st_size
    store.put({"source": "a"}, {"n": 1})

    # Act
    second = store.snapshot("s1")

    # Assert
    assert second == first
    assert second.stat().st_size >= first_size


def test_snapshot_name_may_not_contain_path_separators(tmp_path) -> None:
    """`name` 只是文件名——带路径等于让调用方决定 zip 落哪，那不是它的活。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        store.snapshot("../escape")


def test_restore_makes_deleted_records_come_back(tmp_path) -> None:
    """删了再恢复 == 回来（恢复后本实例的内存态也刷新）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    record_id = store.put({"source": "a"}, {"n": 1})
    archive = store.snapshot("s1")

    store.delete_many([record_id])
    assert store.count() == 0

    # Act
    store.restore(archive)

    # Assert
    assert store.count() == 1


def test_restore_deletes_records_written_after_the_snapshot(tmp_path) -> None:
    """恢复是**以 zip 为准**：快照之后新写的记录会被删掉（"越恢复越多"没有意义）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "before-snap"}, {"n": 1})
    archive = store.snapshot("s1")

    store.put({"source": "after-snap"}, {"n": 2})
    assert store.count() == 2

    # Act
    store.restore(archive)

    # Assert
    assert store.count() == 1
    assert store.filter({"source": "before-snap"})
    assert not store.filter({"source": "after-snap"})


def test_restore_leaves_the_snapshots_directory_alone(tmp_path) -> None:
    """`snapshots/` 不参与还原——拿来还原的 zip 与其他存档都保留。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "a"}, {"n": 1})
    used = store.snapshot("keep-me")
    other = store.snapshot("other")

    # Act
    store.restore(used)

    # Assert
    assert used.is_file()
    assert other.is_file()
