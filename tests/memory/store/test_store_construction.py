"""store 的构造与落盘根：kind 校验、显式 root、缺省根（启动目录）。"""

from __future__ import annotations

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def test_store_rejects_unknown_kind() -> None:
    """未知 kind 在构造时即被断言拒绝（四族之外没有落盘点）。"""

    # Arrange / Act / Assert
    with pytest.raises(AssertionError):
        LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "not_a_kind")


def test_store_creates_kind_directory_under_given_root(tmp_path) -> None:
    """显式 root 下生成 `<root>/<kind>/` 目录（落盘位置就是给定的根）。"""

    # Arrange
    store = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )

    # Act / Assert
    assert (tmp_path / "knowledge_memory").is_dir()
    assert store.kind == "knowledge_memory"


def test_store_default_root_is_memory_under_cwd(tmp_path, monkeypatch) -> None:
    """缺省根落在启动目录下的 `memory/<kind>/`（monkeypatch.chdir 模拟从别处启动）。"""

    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory")
    store.put({"source": "a"}, {"n": 1})

    # Assert
    assert (tmp_path / "memory" / "step_memory").is_dir()
    assert store.count() == 1
