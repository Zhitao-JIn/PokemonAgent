"""store 的分段耗时、语料持久化与向量 sidecar：timings 键、跨实例语料、自动压实。"""

from __future__ import annotations

import json

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory import LocalMemoryStore

_HYBRID_STAGES = {"bm25", "vector", "rrf", "rerank"}
"""hybrid_retrieve 的四段（store.rank 另报 prepare 段，共五段——这里只钉 hybrid 四段）。"""


def test_search_returns_per_stage_timings(tmp_path) -> None:
    """store.search 第二返回值带分段耗时：hybrid 四段齐备且值为非负浮点。"""

    # Arrange
    store = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    store.put({"source": "r1/ep1"}, {}, text="战斗菜单是 2x2 网格")
    store.put({"source": "manual/priors.md"}, {}, text="a 确认 b 取消")

    # Act
    hits, timings = store.search("战斗 菜单 怎么选", limit=5)

    # Assert
    assert hits, "应命中刚写入的两条"
    assert set(timings) >= _HYBRID_STAGES
    assert all(v >= 0.0 for v in timings.values()), timings


def test_refresh_changed_skips_rewrites_with_identical_content(tmp_path) -> None:
    """文件被重写但内容没变（git checkout / pull 的症状）不触发重算（hash 判据）。"""

    # Arrange
    embedder = DeterministicEmbedder()
    store = LocalMemoryStore(embedder, OverlapReranker(), "knowledge_memory", tmp_path)
    store.put({"source": "a.md"}, {}, text="a 确认 b 取消")
    store.put({"source": "b.md"}, {}, text="战斗菜单 2x2")
    before = embedder.calls

    # 模拟 git 重写：按原内容逐字重写每个记录文件（mtime 必变，内容不变）
    for path in (tmp_path / "knowledge_memory").glob("*.md"):
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    # Act
    store.refresh_changed()

    # Assert
    assert embedder.calls == before


def test_bm25_corpus_persists_across_instances(tmp_path) -> None:
    """BM25 的分词语料随 index.json 持久化：新实例（= 重启）不吃进程内状态也能检索。"""

    # Arrange
    store = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    store.put({"source": "r1/ep1"}, {}, text="战斗菜单是 2x2 网格")
    first_hits, _ = store.search("战斗 菜单", limit=5)

    index = json.loads((tmp_path / "knowledge_memory" / "index.json").read_text(encoding="utf-8"))
    assert index["corpus"], "语料应随 index.json 落盘"

    # Act
    fresh = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    second_hits, _ = fresh.search("战斗 菜单", limit=5)

    # Assert
    assert first_hits, "首个实例应能检索"
    assert second_hits, "新实例不吃任何进程内状态也能检索"


def test_sidecar_auto_compacts_when_garbage_rows_dominate(tmp_path) -> None:
    """sidecar 自动压实（探针实证）：行数越过 max(64, 活数×4) 时加载即重写为每 uuid 一行。"""

    # Arrange
    store = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    uids = [store.put({"source": f"a{i}.md"}, {}, text=f"知识{i}") for i in range(3)]
    vectors_file = tmp_path / "knowledge_memory" / "vectors.jsonl"

    # 伪造历史垃圾：追加 100 行重复（越过 max(64, 3×4)=64 阈值）
    lines = [row for row in vectors_file.read_text(encoding="utf-8").splitlines() if row.strip()]
    vectors_file.write_text("\n".join(lines + [lines[-1]] * 100) + "\n", encoding="utf-8")

    # Act
    fresh = LocalMemoryStore(
        DeterministicEmbedder(), OverlapReranker(), "knowledge_memory", tmp_path
    )
    fresh.search("知识", limit=3)  # 触发 _load_vectors → 压实检查

    # Assert
    rows = [
        json.loads(row)
        for row in vectors_file.read_text(encoding="utf-8").splitlines()
        if row.strip()
    ]
    assert len(rows) == len(uids), f"垃圾行远超阈值就应自动压实到每 uuid 一行，实为 {len(rows)} 行"
    assert [r["uuid"] for r in rows] == sorted(uids)
