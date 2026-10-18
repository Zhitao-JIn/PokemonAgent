"""store 的 put / get / get_many：json 与 md 两形态的往返与缺失语义。"""

from __future__ import annotations

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore


def test_put_then_get_round_trips_json_record(tmp_path) -> None:
    """json kind（step_memory）的 metadata、payload、text 原样返回。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    record_id = store.put({"source": "r1/e1"}, {"step": 3}, text="按键记录")

    # Act
    got = store.get(record_id)

    # Assert
    assert got is not None
    metadata, payload, text = got
    assert metadata == {"source": "r1/e1"}
    assert payload == {"step": 3}
    assert text == "按键记录"


def test_put_then_get_round_trips_markdown_record(tmp_path) -> None:
    """md kind（knowledge_memory）的 frontmatter 与正文原样返回。"""

    # Arrange
    store = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    record_id = store.put({"source": "manual/priors.md"}, {"topic": "dialog"}, text="a 确认 b 取消")

    # Act
    got = store.get(record_id)

    # Assert
    assert got is not None
    metadata, payload, text = got
    assert metadata == {"source": "manual/priors.md"}
    assert payload == {"topic": "dialog"}
    assert text == "a 确认 b 取消"


def test_get_returns_none_for_unknown_uuid(tmp_path) -> None:
    """从未写入的 uuid → `None`（不存在不是空三元组）。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)

    # Act / Assert
    assert store.get("no-such-uuid") is None


def test_get_returns_none_when_record_file_removed_outside_index(tmp_path) -> None:
    """CP2 回归：记录文件被外部删掉、索引尚未对账时，get 第一次就返回 None。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    record_id = store.put({"source": "s"}, {"n": 0}, text="正文")
    record = tmp_path / "step_memory" / f"{record_id}.json"
    record.unlink()

    # Act
    first_get = store.get(record_id)
    second_get = store.get(record_id)

    # Assert
    assert first_get is None
    assert second_get is None


def test_get_many_skips_unknown_uuids(tmp_path) -> None:
    """未知 uuid 不出现在结果中，已知的保持请求顺序。"""

    # Arrange
    store = LocalMemoryStore(DeterministicEmbedder(), OverlapReranker(), "step_memory", tmp_path)
    first = store.put({"source": "s"}, {"n": 1}, text="一")
    second = store.put({"source": "s"}, {"n": 2}, text="二")

    # Act
    got = store.get_many([second, "missing", first])

    # Assert
    assert [uuid for uuid, _metadata, _payload, _text in got] == [second, first]
