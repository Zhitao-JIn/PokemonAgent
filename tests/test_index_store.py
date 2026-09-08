"""`MemoryIndexStore` 测试（`interfaces/memory/memory_index_port.py` 契约 +
`docs/ROADMAP.md` 第 24 条）。

覆盖：写入生成唯一 uuid、点查（单条/批量，含不存在的 id）、过滤检索的
多字段交集与对称性（无主键）、语义检索的候选范围收窄与"无 text 搜不到"、
删除后索引与磁盘同步更新、重启后从磁盘重建索引与向量缓存的持久化一致性。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pokemon_agent.memory import MemoryIndexStore


class _StubEmbeddingProvider:
    """确定性假 embedding：按固定字表数字符，不依赖真实模型。"""

    _ALPHABET = list("abcdefghijklmnopqrstuvwxyz迷路球洞穴森林商店")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.count(c)) for c in self._ALPHABET] for text in texts]


class _StubRerankerProvider:
    """确定性假精排：按查询与文档的字符集合交集大小打分。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        qset = set(query)
        return [float(len(qset & set(doc))) for doc in documents]


def _store(directory: Path) -> MemoryIndexStore:
    return MemoryIndexStore(
        embedder=_StubEmbeddingProvider(), reranker=_StubRerankerProvider(), directory=directory
    )


def test_put_generates_unique_uuid_and_get_roundtrips():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid1 = store.put(metadata={"project": "poke", "step": "1"}, payload={"obs": "a"})
    uid2 = store.put(metadata={"project": "poke", "step": "2"}, payload={"obs": "b"})
    assert uid1 != uid2

    meta, payload = store.get(uid1)
    assert meta == {"project": "poke", "step": "1"}
    assert payload == {"obs": "a"}
    assert store.get("no-such-uuid") is None


def test_get_many_skips_missing_and_preserves_fields():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid1 = store.put(metadata={"episode_id": "ep1"}, payload={"obs": "a"})
    uid2 = store.put(metadata={"episode_id": "ep1"}, payload={"obs": "b"})

    got = store.get_many([uid1, "missing-uuid", uid2])
    assert len(got) == 2
    assert {u for u, _, _ in got} == {uid1, uid2}


def test_filter_is_symmetric_across_fields_no_primary_key():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid1 = store.put(metadata={"episode_id": "ep1", "map": "39", "step": "3"}, payload={})
    uid2 = store.put(metadata={"episode_id": "ep1", "map": "39", "step": "5"}, payload={})
    uid3 = store.put(metadata={"episode_id": "ep2", "map": "40", "step": "1"}, payload={})

    assert set(store.filter({"episode_id": "ep1"})) == {uid1, uid2}
    # 任意字段组合都能查、结果一致，字段之间没有主次之分
    assert set(store.filter({"episode_id": "ep1", "map": "39"})) == {uid1, uid2}
    assert set(store.filter({"map": "39", "episode_id": "ep1"})) == {uid1, uid2}
    assert set(store.filter({"episode_id": "ep1", "step": "5"})) == {uid2}
    assert set(store.filter({})) == {uid1, uid2, uid3}
    assert store.filter({"map": "999"}) == []


def test_search_scopes_by_conditions_and_skips_records_without_text():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid_cave = store.put(
        metadata={"episode_id": "ep1"}, payload={}, text="玩家走进了一个黑暗的洞穴"
    )
    store.put(metadata={"episode_id": "ep2"}, payload={}, text="玩家在商店里买东西")
    uid_no_text = store.put(metadata={"episode_id": "ep1"}, payload={"obs": "无文本"})

    results = store.search("洞穴", limit=5)
    assert uid_cave in results
    assert uid_no_text not in results, "没写 text 的记录不该被语义检索命中"

    scoped_out = store.search("洞穴", limit=5, conditions={"episode_id": "ep2"})
    assert uid_cave not in scoped_out, "conditions 圈定的候选范围之外不该被检索到"

    empty_scope = store.search("洞穴", limit=5, conditions={"episode_id": "no-such-episode"})
    assert empty_scope == []


def test_delete_many_removes_from_index_and_disk():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid1 = store.put(metadata={"episode_id": "ep1"}, payload={})
    uid2 = store.put(metadata={"episode_id": "ep1"}, payload={})

    store.delete_many([uid1])
    assert store.get(uid1) is None
    assert set(store.filter({"episode_id": "ep1"})) == {uid2}

    reloaded = _store(d)
    assert reloaded.get(uid1) is None
    assert set(reloaded.filter({"episode_id": "ep1"})) == {uid2}


def test_reload_from_disk_rebuilds_index_and_search():
    d = Path(tempfile.mkdtemp())
    store = _store(d)
    uid = store.put(
        metadata={"episode_id": "ep1", "map": "39"}, payload={"obs": "x"}, text="商店里买东西"
    )
    del store  # 模拟进程重启：丢掉内存态，只留盘上的 records.jsonl

    reloaded = _store(d)
    assert set(reloaded.filter({"episode_id": "ep1"})) == {uid}
    assert set(reloaded.filter({"episode_id": "ep1", "map": "39"})) == {uid}
    assert uid in reloaded.search("商店", limit=5)

    shutil.rmtree(d, ignore_errors=True)
