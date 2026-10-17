"""`LocalMemoryStore` / `MemoryTool` 落盘根 + 快照往返的用法示范（0916）。

**为什么这个文件值钱**："数据落在哪"从写死仓库根改为启动时决定（0916）之后，
四条行为没有编译器保护，只有测试能钉住：

1. `LocalMemoryStore` 不传 `root` → 落在**启动目录**下的 `memory/<kind>/`；
2. `MemoryCapability` 不传 `memory_root` → 四族共用一个根，各占其下 `<kind>/`；
3. `snapshot(name)` 把**整个记忆根**打成 `<根>/snapshots/<name>.zip`，且 zip 里
   **不含 `snapshots/` 自己**（否则每拍一次就自我嵌套一层）；
4. `restore(archive)` 是**覆盖**——zip 里有谁就是谁，zip 里没有的原样留着；
   且恢复后内存态要刷新（否则恢复回来的那局会被旧的 max 缓存挡住）。

**不连网、不碰模拟器、不调模型、不往真实启动目录写**：embedder / reranker 用
最小假件（构造期不被调用），落盘根全部显式给 `tmp_path` 或 chdir 进 `tmp_path`。
"""

from __future__ import annotations

import pathlib
import zipfile
from collections.abc import Iterator

import pytest
from _doubles.memory_server import memory_server_context

from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.memory import LocalMemoryStore
from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
)


class _FakeEmbedder:
    """构造期不被调用的最小假件（真实现是 `memory/fastembed_text.py`）。

    `calls` 累计**收到的文本条数**——`refresh_changed` 的"重算没重算"只有
    通过它才观测得到（mtime / hash 的玄机对调用方不可见，这正是契约）。"""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[0.0] * 4 for _ in texts]


class _FakeReranker:
    """同上（真实现是 `memory/fastembed_reranker.py`）。"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0] * len(documents)


_KINDS = ("step_memory", "object_memory", "episode_memory", "knowledge_memory", "run_memory")


def _store(root: pathlib.Path | None = None, kind: str = "step_memory") -> LocalMemoryStore:
    """造一个 `LocalMemoryStore`（root 缺省时走"启动目录"那条路）。"""
    return LocalMemoryStore(_FakeEmbedder(), _FakeReranker(), kind, root)


def _put(store: LocalMemoryStore, *, episode_id: str = "e0", step: int = 0) -> str:
    """往任一族塞一条最小记录（`metadata` 的值必须是 `str`）。"""
    return store.put({"run_id": "r", "episode_id": episode_id, "step": str(step)}, {"step": step})


def _snap(tool: MemoryTool, name: str = "s1") -> pathlib.Path:
    """拍一张快照并拿回 zip 路径（测试里反复用，收短调用点）。"""
    return pathlib.Path(
        tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name=name)).archive
    )


@pytest.fixture
def connected(tmp_path: pathlib.Path) -> Iterator[tuple[MemoryCapability, MemoryTool]]:
    """服务端根与客户端快照根分开，通过 MCP 信封往返。"""
    with memory_server_context(tmp_path / "server", tmp_path) as pair:
        yield pair


# ---- 落盘根 ----


def test_store_default_root_is_the_startup_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不传 `root` 时落盘根是**启动目录**下的 `memory/`（0916 起）。

    `LocalMemoryStore` 不再从 `__file__` 回溯仓库根——"数据落在哪"由启动方决定
    （`--memory-root` → `build_real` → `MemoryTool.build` → 这里）。
    monkeypatch.chdir 模拟"从别处启动"。
    """
    monkeypatch.chdir(tmp_path)
    store = _store()

    _put(store)

    assert (tmp_path / "memory" / "step_memory").is_dir()
    assert store.count() == 1


def test_tool_defaults_put_each_family_under_the_shared_root(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """四族共用一个记忆根，各占其下 `<kind>/`——**只有一个开关**管四族。

    与 0916 之前的缺省布局逐字一致（一个 `memory/`、四个子文件夹），
    区别只在于"根在哪"由**一个**参数决定。
    """
    monkeypatch.chdir(tmp_path)
    MemoryCapability(_FakeEmbedder(), _FakeReranker())

    for kind in _KINDS:
        assert (tmp_path / "memory" / kind).is_dir(), kind


def test_explicit_memory_root_wins_over_the_default(tmp_path: pathlib.Path) -> None:
    """显式给 `memory_root` 时四族全落在它下面（缺省不被用到）。"""
    MemoryCapability(_FakeEmbedder(), _FakeReranker(), memory_root=tmp_path)

    for kind in _KINDS:
        assert (tmp_path / kind).is_dir(), kind


def test_store_explicit_root_wins_over_the_default(tmp_path: pathlib.Path) -> None:
    """`LocalMemoryStore` 显式传 root 时落盘位置就是给定的根。"""
    store = _store(tmp_path, "knowledge_memory")

    _put(store)

    assert (tmp_path / "knowledge_memory").is_dir()


# ---- 快照 / 恢复 ----


def test_snapshot_zips_the_whole_root_and_excludes_itself(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """快照打的是**整个记忆根**，落在 `<根>/snapshots/<name>.zip`，且里面没有 `snapshots/`。

    若 `snapshots/` 也进 zip，第二次快照就会把第一次的 zip 套进去——体积指数增长。
    四族都是同一个根下的子文件夹，所以一张快照天然覆盖四族。
    """
    capability, tool = connected
    _put(capability._store("act"))

    archive = _snap(tool)

    assert archive == tmp_path / "snapshots" / "s1.zip"
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert any(name.startswith("step_memory/") for name in names), names
    assert not any(name.startswith("snapshots/") for name in names), names


def test_snapshot_overwrites_a_previous_one_with_the_same_name(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """同名快照覆盖——`name` 是调用方给的标识，不是一个自增号。"""
    capability, tool = connected
    req = FromHarnessToMemoryToolSnapshotMemoryReq(name="s1")

    first = _snap(tool, req.name)
    first_size = first.stat().st_size
    _put(capability._store("act"), episode_id="e1")
    second = _snap(tool, req.name)

    assert second == first
    assert second.stat().st_size >= first_size


def test_snapshot_name_may_not_contain_path_separators(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """`name` 只是文件名——带路径等于让 harness 决定 zip 落哪，那不是它的活。"""
    capability, tool = connected

    with pytest.raises(AssertionError):
        tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="../escape"))


def test_restore_makes_deleted_records_come_back(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """删了再恢复 == 回来。这是快照存在的理由：`delete_many` 之后没有第二次机会。"""
    capability, tool = connected
    record_id = _put(capability._store("act"))
    archive = _snap(tool)

    capability._store("act").delete_many([record_id])
    assert capability._store("act").count() == 0

    tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(archive)))

    assert capability._store("act").count() == 1, "恢复后内存态也要刷新（reload + 清 max 缓存）"


def test_restore_deletes_records_written_after_the_snapshot(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """恢复是**以 zip 为准**：快照之后新写的记录会被删掉。

    留下快照之后才写进去的那些，就不是那一刻了——"越恢复越多"会让快照失去
    "能整体还原"的意义。要"只加不减"是另一套语义，本方法不做。
    """
    capability, tool = connected
    _put(capability._store("act"), episode_id="before-snap")
    archive = _snap(tool)

    _put(capability._store("act"), episode_id="after-snap")
    assert capability._store("act").count() == 2

    tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(archive)))

    assert capability._store("act").count() == 1, "以 zip 为准——快照之后写的那条该被删掉"
    assert capability._store("act").filter({"episode_id": "before-snap"}), "zip 里那条必须还在"
    assert not capability._store("act").filter({"episode_id": "after-snap"}), "zip 里没有的不该留下"


def test_restore_leaves_the_snapshots_directory_alone(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """`snapshots/` 不参与还原——恢复一次就把存档自己删了，那份档就再也用不上。"""
    capability, tool = connected
    _put(capability._store("act"))
    used = _snap(tool, "keep-me")
    other = _snap(tool, "other")

    tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(used)))

    assert used.is_file(), "拿来还原的那份 zip 不该被删"
    assert other.is_file(), "别的存档也不该被删"


def test_restore_refreshes_every_family_not_just_step_memory(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """四族都要 `reload`——`restore()` 只刷它自己那个实例（`step_memory`）。

    只在 step 上刷、别的族不刷的话：恢复回来的摘要"文件在盘上但索引里查不到"，
    直到进程重启才自愈。这个测试钉住 `restore_memory` 里那个 for 循环。
    """
    capability, tool = connected
    summary_id = _put(capability._store("episode"), episode_id="ep-1")
    archive = _snap(tool)

    capability._store("episode").delete_many([summary_id])
    assert capability._store("episode").count() == 0

    tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(archive)))

    assert capability._store("episode").count() == 1, "episode_memory 的内存态也要跟着刷"


def test_restore_rejects_unsafe_entries_before_touching_the_library(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """能力层在删除前拒绝含不安全条目的整个归档。"""
    capability, tool = connected
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped.json", "{}")
        zf.writestr("not_a_kind/whatever.json", "{}")
        zf.writestr("step_memory/../../escaped2.json", "{}")

    with pytest.raises(AssertionError, match="不安全"):
        tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(evil)))
    assert not (tmp_path.parent / "escaped.json").exists()
    assert not (tmp_path.parent / "escaped2.json").exists()


def test_knowledge_store_search_returns_per_stage_timings(tmp_path: pathlib.Path) -> None:
    """知识检索（store 层）**自带分段耗时**（0928 324）：五段 prepare/bm25/vector/
    rrf/rerank 齐全且非负——能力面收敛（recall/memorize）后 timings 不再上 Port，
    这笔账在 store 层直测（聚合靠 langfuse 拉账）。"""
    from pokemon_agent.memory import LocalMemoryStore

    store = LocalMemoryStore(_FakeEmbedder(), _FakeReranker(), "knowledge_memory", tmp_path)
    store.put(
        metadata={"source": "r1/ep1", "topic": "battle_menu"},
        payload={},
        text="战斗菜单是 2x2 网格",
    )
    store.put(
        metadata={"source": "manual/priors.md", "topic": "dialog_confirm"},
        payload={},
        text="a 确认 b 取消",
    )

    hits, timings = store.search("战斗 菜单 怎么选", limit=5)

    assert hits, "应命中刚写入的两条"
    assert set(timings) == {"prepare", "bm25", "vector", "rrf", "rerank"}
    assert all(v >= 0.0 for v in timings.values()), timings


def test_refresh_changed_skips_rewrites_with_identical_content(
    tmp_path: pathlib.Path,
) -> None:
    """文件被**重写但内容没变**（git checkout / pull 的症状）不触发重算：
    refresh_changed 的判据是内容 hash，mtime 只是预筛（0928 326）。"""
    embedder = _FakeEmbedder()
    store = LocalMemoryStore(embedder, _FakeReranker(), "knowledge_memory", tmp_path)
    store.put(metadata={"source": "a.md"}, payload={}, text="a 确认 b 取消")
    store.put(metadata={"source": "b.md"}, payload={}, text="战斗菜单 2x2")
    before = embedder.calls

    # 模拟 git 重写：按原内容逐字重写每个记录文件（mtime 必变，内容不变）
    for path in tmp_path.glob("*.md"):
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    import os

    for path in tmp_path.glob("*.md"):
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 5))

    store.refresh_changed()

    assert embedder.calls == before, (
        "内容一字未变的重写不该重算向量——mtime 误判正是 vectors.jsonl 膨胀的帮凶"
    )


def test_refresh_changed_recomputes_when_content_actually_changes(
    tmp_path: pathlib.Path,
) -> None:
    """内容**真的变了**就重算——hash 判据不能把真实编辑也吞掉。"""
    embedder = _FakeEmbedder()
    store = LocalMemoryStore(embedder, _FakeReranker(), "knowledge_memory", tmp_path)
    store.put(metadata={"source": "a.md"}, payload={}, text="a 确认 b 取消")
    before = embedder.calls

    record = next((tmp_path / "knowledge_memory").glob("*.md"))
    rewritten = record.read_text(encoding="utf-8").replace("a 确认 b 取消", "a 确定 b 取消")
    record.write_text(rewritten, encoding="utf-8")
    import os

    stat = record.stat()
    os.utime(record, (stat.st_atime, stat.st_mtime + 5))

    store.refresh_changed()

    assert embedder.calls > before, "正文真变了就该重算——热更新性质不能被 hash 判据吞掉"


def test_bm25_corpus_persists_across_instances(
    tmp_path: pathlib.Path, connected: tuple[MemoryCapability, MemoryTool]
) -> None:
    """BM25 的**分词语料随 index.json 持久化**（0928 326）：换一个实例
    （= 重启进程）检索，语料直接吃盘上的，不重分词。"""
    import json

    from pokemon_agent.schemas.harness import (
        FromHarnessToMemoryToolMemorizeRecord,
        FromHarnessToMemoryToolMemorizeReq,
        FromHarnessToMemoryToolRecallReq,
    )
    from pokemon_agent.schemas.memory import KnowledgeRecord

    capability, tool = connected
    tool.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[
                FromHarnessToMemoryToolMemorizeRecord(
                    kind="knowledge",
                    payload=KnowledgeRecord(
                        source="r1/ep1",
                        run_id="r1",
                        episode_id="ep1",
                        topic="battle_menu",
                        text="战斗菜单是 2x2 网格",
                    ).model_dump(),
                )
            ]
        )
    )
    tool.recall(FromHarnessToMemoryToolRecallReq(query="战斗 菜单", limit=5))

    index = json.loads(
        (capability.root / "knowledge_memory" / "index.json").read_text(encoding="utf-8")
    )
    assert index["corpus"], "语料应随 index.json 落盘"

    fresh = LocalMemoryStore(_FakeEmbedder(), _FakeReranker(), "knowledge_memory", capability.root)
    hits, timings = fresh.search("战斗 菜单", limit=5)
    assert hits, "新实例不吃任何进程内状态也能检索"
    assert set(timings) == {"prepare", "bm25", "vector", "rrf", "rerank"}


def test_embedding_rank_scores_with_numpy_matrix_include_zero_vectors() -> None:
    """向量打分 numpy 化（0928 327）的边界行为：正交向量按余弦降序、
    零向量得 0 分垫底——与旧 `_cosine` 的边界行为一致，不因矩阵化改变。"""
    from pokemon_agent.memory.retrieval import embedding_rank

    class _OrthogonalEmbedder:
        """三篇文档两两正交、query 与第一篇同向；再加一篇全零向量。"""

        def embed(self, texts: list[str]) -> list[list[float]]:
            table = {
                "query": [1.0, 0.0],
                "same": [2.0, 0.0],  # 与 query 同向，余弦 1.0
                "perp": [0.0, 3.0],  # 正交，余弦 0.0
                "zero": [0.0, 0.0],  # 零范数，余弦 0.0（旧实现的边界行为）
            }
            return [table[t] for t in texts]

    ranked = embedding_rank(
        "query", ["same", "perp", "zero"], _OrthogonalEmbedder(), document_vectors=None
    )

    assert ranked[0] == 0, "与 query 同向的文档应排第一"
    assert ranked[-1] == 2, "零向量文档 norm=0，得 0 分垫底（不炸、不 NaN）"


def test_sidecar_auto_compacts_when_garbage_rows_dominate(tmp_path: pathlib.Path) -> None:
    """sidecar 自动压实（0928 327）：垃圾行远超活行时加载即重写——
    326 的手动压实升级成机械规则，不再依赖人盯。"""
    import json

    store = LocalMemoryStore(_FakeEmbedder(), _FakeReranker(), "knowledge_memory", tmp_path)
    uids = [
        store.put(metadata={"source": f"a{i}.md"}, payload={}, text=f"知识{i}") for i in range(3)
    ]
    vectors_file = tmp_path / "knowledge_memory" / "vectors.jsonl"

    # 伪造历史垃圾：追加 100 行重复（模拟反复重算的年代，越过 max(64, ×4) 阈值）
    lines = vectors_file.read_text(encoding="utf-8").splitlines()
    junk = lines[-1]
    vectors_file.write_text("\n".join(lines + [junk] * 100) + "\n", encoding="utf-8")
    assert len(vectors_file.read_text(encoding="utf-8").splitlines()) > 64

    fresh = LocalMemoryStore(_FakeEmbedder(), _FakeReranker(), "knowledge_memory", tmp_path)
    _ = fresh.search("知识", limit=3)  # 触发 _load_vectors → 压实检查

    rows = [
        json.loads(row)
        for row in vectors_file.read_text(encoding="utf-8").splitlines()
        if row.strip()
    ]
    assert len(rows) == len(uids), f"垃圾行远超阈值就应自动压实到每 uuid 一行，实为 {len(rows)} 行"
    assert [r["uuid"] for r in rows] == sorted(uids)
