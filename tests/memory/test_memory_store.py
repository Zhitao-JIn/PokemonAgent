"""`MemoryCapability` / `MemoryTool` 的落盘根与快照恢复：能力层用例（CP7 处理）。

store 层的直调用例已迁去 `tests/memory/store/`（CP6，spec 第四节逐条映射）；本文件
只剩经 `MemoryCapability` / `MemoryTool` 信封的四条，随 CP7 一并迁移或删除。

**不连网、不碰模拟器、不调模型、不往真实启动目录写**：embedder / reranker 用最小
假件（构造期不被调用），落盘根全部显式给 `tmp_path` 或 chdir 进 `tmp_path`。
"""

from __future__ import annotations

import pathlib
import zipfile
from collections.abc import Iterator

import pytest
from _doubles.memory_server import memory_server_context

from pokemon_agent.mcpclient.memory_local import MemoryTool
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


_KINDS = ("step_memory", "object_memory", "episode_memory", "knowledge_memory")


def _put(store, *, episode_id: str = "e0", step: int = 0) -> str:
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


# ---- 快照 / 恢复 ----


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
