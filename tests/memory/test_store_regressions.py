"""CP1（496）回归：content hash 随 index.json 持久化后，重启 + mtime 变不再整库重算向量。

O1 修复前 `_hashes` 基线不落盘——进程重启后 `refresh_changed()` 会把 md 类内容一字没变的整库
向量白算一遍（git checkout / pull 重写工作区文件的常见场景）。这里钉三条：重启后内容没变不
重算（=0）、同实例 touch 不重算（控制组）、重启后真改内容仍重算（=1）。

**不连网、不碰模拟器、不调模型、不 sleep**：embedder / reranker 用最小手写假件，mtime 用
`os.utime` 改，落盘根全部显式给 `tmp_path`。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pokemon_agent.memory import LocalMemoryStore


class _CountingEmbedder:
    """计数假 embedder：`calls` 累计**收到的文本条数**（真实现是 `memory/fastembed_text.py`）。

    不调真模型；`refresh_changed` 的"重算没重算"只有通过它才观测得到（mtime / hash 的玄机
    对调用方不可见，这正是契约）。"""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[0.0] * 4 for _ in texts]


class _NoRerank:
    """rerank 占位：store 构造需要，本测试不跑语义检索、不该调到它——调到即炸。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        raise AssertionError("本测试不该触发 rerank")


class _ScoringRerank:
    """rerank 占位：按文档顺序给递减分数，让 search 的正常路径能跑完（本测试不验排序）。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [float(len(documents) - i) for i in range(len(documents))]


_TOUCHED = 1_000_000_000.0
"""一个与"现在"明显不同的固定 mtime（`os.utime` 用；避免 sleep 等 mtime 变）。"""


def _record(tmp_path: Path, record_id: str) -> Path:
    """md 类记录文件路径（`<root>/knowledge_memory/<uuid>.md`，布局见 store 模块 docstring）。"""
    return tmp_path / "knowledge_memory" / f"{record_id}.md"


def test_refresh_changed_does_not_reembed_after_restart_when_content_unchanged(
    tmp_path: Path,
) -> None:
    """重启后 mtime 变但内容一字没变：refresh_changed 不重算任何向量（hash 基线已随索引落盘）。"""

    # Arrange
    first = LocalMemoryStore(_CountingEmbedder(), _NoRerank(), "knowledge_memory", root=tmp_path)
    ids = [first.put({"source": "s"}, {"n": i}, text=f"第 {i} 段正文") for i in range(3)]

    restarted_embedder = _CountingEmbedder()
    restarted = LocalMemoryStore(restarted_embedder, _NoRerank(), "knowledge_memory", root=tmp_path)
    for record_id in ids:
        os.utime(_record(tmp_path, record_id), (_TOUCHED, _TOUCHED))

    # Act
    restarted.refresh_changed()

    # Assert
    assert restarted_embedder.calls == 0


def test_refresh_changed_same_instance_touch_does_not_reembed(tmp_path: Path) -> None:
    """同一实例里 touch（mtime 变、内容没变）：不重算——控制组，修复前后都应为 0。"""

    # Arrange
    embedder = _CountingEmbedder()
    store = LocalMemoryStore(embedder, _NoRerank(), "knowledge_memory", root=tmp_path)
    record_id = store.put({"source": "s"}, {"n": 0}, text="正文")
    os.utime(_record(tmp_path, record_id), (_TOUCHED, _TOUCHED))
    before = embedder.calls

    # Act
    store.refresh_changed()

    # Assert
    assert embedder.calls == before


def test_refresh_changed_reembeds_when_content_really_changes_after_restart(tmp_path: Path) -> None:
    """重启后内容真变了：refresh_changed 重算那一条的向量（hash 基线对不上），计数为 1。"""

    # Arrange
    first = LocalMemoryStore(_CountingEmbedder(), _NoRerank(), "knowledge_memory", root=tmp_path)
    record_id = first.put({"source": "s"}, {"n": 0}, text="旧正文")

    restarted_embedder = _CountingEmbedder()
    restarted = LocalMemoryStore(restarted_embedder, _NoRerank(), "knowledge_memory", root=tmp_path)
    path = _record(tmp_path, record_id)
    path.write_text(path.read_text(encoding="utf-8") + "真的改了。\n", encoding="utf-8")

    # Act
    restarted.refresh_changed()

    # Assert
    assert restarted_embedder.calls == 1


def test_get_returns_none_when_record_file_removed_outside_index(tmp_path: Path) -> None:
    """记录文件被外部删掉、索引尚未对账：get 第一次就返回 None（契约），不再返回空三元组。"""

    # Arrange
    store = LocalMemoryStore(_CountingEmbedder(), _NoRerank(), "step_memory", root=tmp_path)
    record_id = store.put({"source": "s"}, {"n": 0}, text="正文")
    record = tmp_path / "step_memory" / f"{record_id}.json"
    record.unlink()

    # Act
    first_get = store.get(record_id)
    second_get = store.get(record_id)

    # Assert
    assert first_get is None
    assert second_get is None


def test_search_rejects_non_positive_limit(tmp_path: Path) -> None:
    """limit<=0 在 search 入口就断言拒绝：不再按切片语义静默返回（limit=-1 曾返回 n-1 条）。"""

    # Arrange
    store = LocalMemoryStore(_CountingEmbedder(), _ScoringRerank(), "step_memory", root=tmp_path)
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
