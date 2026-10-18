"""capability 的 snapshot / restore：整根快照、不安全条目整包拒绝、恢复后单调缓存重置。"""

from __future__ import annotations

import zipfile

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory

_RUN = "r1"
_EP = "e1"


def _capability(tmp_path) -> MemoryCapability:
    return MemoryCapability(DeterministicEmbedder(), OverlapReranker(), memory_root=tmp_path)


def _act(step: int = 1) -> dict:
    obs = ActMemory.Observation(step=step, status=f"第 {step} 步。")
    return ActMemory(
        before=obs, action="up", after=obs, step=step, episode_id=_EP, run_id=_RUN
    ).model_dump()


def _episode(episode_id: str, markdown: str = "", summary: str = "") -> dict:
    return EpisodeMemory(
        episode_id=episode_id,
        run_id=_RUN,
        goal="g",
        steps=1,
        summary=summary,
        quality_score=0.0,
        quality_rationale="-",
        markdown=markdown,
    ).model_dump()


def test_snapshot_then_restore_brings_back_memorized_records(tmp_path) -> None:
    """快照后新写的记录在 restore 后消失，快照那一刻的能经 recall 取回（以 zip 为准）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=1)}])
    archive = capability.snapshot("s1")
    capability.memorize([{"kind": "act", "payload": _act(step=2)}])

    # Act
    capability.restore(archive)

    # Assert
    items = capability.recall("", {"episode_id": _EP})
    assert [item["payload"]["step"] for item in items] == [1]


def test_restore_rejects_archive_with_unsafe_entry_and_leaves_library_unchanged(tmp_path) -> None:
    """含 `..` 条目的 zip 在删除前被整包拒绝（AssertionError），库保持不变。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=1)}])
    before = capability.recall("", {"episode_id": _EP})
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped.json", "{}")
        zf.writestr("step_memory/../../escaped2.json", "{}")

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.restore(evil)
    assert capability.recall("", {"episode_id": _EP}) == before
    assert not (tmp_path.parent / "escaped.json").exists()
    assert not (tmp_path.parent / "escaped2.json").exists()


def test_restore_resets_step_monotonic_cache(tmp_path) -> None:
    """restore 把 append 单调缓存清掉：恢复到只含 step=0 的快照后，step=1 能写进去。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=0)}])
    archive = capability.snapshot("s0")
    capability.memorize([{"kind": "act", "payload": _act(step=5)}])

    # Act
    capability.restore(archive)
    stored = capability.memorize([{"kind": "act", "payload": _act(step=1)}])

    # Assert
    assert [entry["kind"] for entry in stored] == ["act"], "缓存已重置，step=1 不被旧的 max=5 拦住"
