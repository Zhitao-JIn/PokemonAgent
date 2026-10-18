"""store 的 refresh_changed：mtime 预筛 + 内容 hash 判据，md 类增量重算、json 类空转。"""

from __future__ import annotations

import os

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore

_TOUCHED = 1_000_000_000.0
"""一个与"现在"明显不同的固定 mtime（os.utime 用；避免 sleep 等 mtime 变）。"""


def test_refresh_changed_is_noop_for_json_kind(tmp_path) -> None:
    """json kind 调用 refresh_changed 不改变 embedder 计数（没有可重算的 md）。"""

    # Arrange
    embedder = DeterministicEmbedder()
    store = LocalMemoryStore(embedder, OverlapReranker(), "step_memory", tmp_path)
    store.put({"source": "s"}, {"n": 0}, text="正文")
    before = embedder.calls

    # Act
    store.refresh_changed()

    # Assert
    assert embedder.calls == before


def test_refresh_changed_reembeds_only_the_edited_markdown_record(tmp_path) -> None:
    """两条 md 只改一条内容 → 只重算那一条（计数 +1）。"""

    # Arrange
    embedder = DeterministicEmbedder()
    store = LocalMemoryStore(embedder, OverlapReranker(), "knowledge_memory", tmp_path)
    store.put({"source": "a.md"}, {}, text="a 确认 b 取消")
    before = embedder.calls

    record = next((tmp_path / "knowledge_memory").glob("*.md"))
    record.write_text(
        record.read_text(encoding="utf-8").replace("a 确认 b 取消", "a 确定 b 取消"),
        encoding="utf-8",
    )
    stat = record.stat()
    os.utime(record, (stat.st_atime, stat.st_mtime + 5))

    # Act
    store.refresh_changed()

    # Assert
    assert embedder.calls == before + 1


def test_refresh_changed_does_not_reembed_after_restart_when_content_unchanged(
    tmp_path,
) -> None:
    """CP1 回归：重启后 mtime 变但内容一字没变，refresh_changed 不重算任何向量。"""

    # Arrange
    first = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    ids = [first.put({"source": "s"}, {"n": i}, text=f"第 {i} 段正文") for i in range(3)]

    restarted_embedder = DeterministicEmbedder()
    restarted = LocalMemoryStore(
        restarted_embedder, OverlapReranker(), "knowledge_memory", tmp_path
    )
    for record_id in ids:
        os.utime(tmp_path / "knowledge_memory" / f"{record_id}.md", (_TOUCHED, _TOUCHED))

    # Act
    restarted.refresh_changed()

    # Assert
    assert restarted_embedder.calls == 0


def test_refresh_changed_same_instance_touch_does_not_reembed(tmp_path) -> None:
    """CP1 回归（控制组）：同一实例里 touch（mtime 变、内容没变）不重算。"""

    # Arrange
    embedder = DeterministicEmbedder()
    store = LocalMemoryStore(embedder, OverlapReranker(), "knowledge_memory", tmp_path)
    record_id = store.put({"source": "s"}, {"n": 0}, text="正文")
    os.utime(tmp_path / "knowledge_memory" / f"{record_id}.md", (_TOUCHED, _TOUCHED))
    before = embedder.calls

    # Act
    store.refresh_changed()

    # Assert
    assert embedder.calls == before


def test_refresh_changed_reembeds_when_content_really_changes_after_restart(tmp_path) -> None:
    """CP1 回归：重启后内容真变了，refresh_changed 重算那一条（计数 = 1）。"""

    # Arrange
    first = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    record_id = first.put({"source": "s"}, {"n": 0}, text="旧正文")

    restarted_embedder = DeterministicEmbedder()
    restarted = LocalMemoryStore(
        restarted_embedder, OverlapReranker(), "knowledge_memory", tmp_path
    )
    path = tmp_path / "knowledge_memory" / f"{record_id}.md"
    path.write_text(path.read_text(encoding="utf-8") + "真的改了。\n", encoding="utf-8")

    # Act
    restarted.refresh_changed()

    # Assert
    assert restarted_embedder.calls == 1
