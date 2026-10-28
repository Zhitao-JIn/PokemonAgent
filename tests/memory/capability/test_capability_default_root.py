"""capability 的缺省根与显式根：四族共用一个记忆根（原 test_memory_store.py 104/119/238）。

原文件随 CP7 删除；这三条加 root 属性一条是能力层契约（经 `MemoryCapability` 公开
方法，D1），store 层直调用例在 `tests/memory/store/`（CP6）。
"""

from __future__ import annotations

from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory, TaskMemory

_RUN = "r1"
_EP = "e1"
_KINDS = ("step_memory", "task_memory", "episode_memory", "run_memory", "knowledge_memory")


def _capability(tmp_path) -> MemoryCapability:
    return MemoryCapability(DeterministicEmbedder(), OverlapReranker(), memory_root=tmp_path)


def _act(step: int = 1) -> dict:
    obs = ActMemory.Observation(facts={"overlay": "none"}, step=step)
    return ActMemory(
        before=obs,
        action="up",
        after=obs,
        step=step,
        episode_id=_EP,
        run_id=_RUN,
        observations=[],
        outcome=None,
    ).model_dump()


def _task() -> dict:
    return TaskMemory(
        run_id=_RUN,
        episode_id=_EP,
        task_id="t1",
        goal="走到草丛",
        termination="goal_done",
        reason="到达",
        steps_used=3,
        total_acts=1,
        summary="沿空地向北走到草丛边。",
        quality_score=0.5,
        quality_rationale="常规移动。",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _episode(episode_id: str) -> dict:
    return EpisodeMemory(
        episode_id=episode_id,
        run_id=_RUN,
        goal="g",
        steps=1,
        summary="一。",
        quality_score=0.0,
        quality_rationale="-",
        markdown="一。",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _knowledge(text: str = "草丛里会遇到野生宝可梦。") -> dict:
    return {
        "topic": "草丛",
        "text": text,
        "source": f"{_RUN}/{_EP}",
        "run_id": _RUN,
        "episode_id": _EP,
    }


def _run(summary: str) -> dict:
    return RunMemory(
        run_id=_RUN,
        run_goal="走到草丛",
        episodes=1,
        succeeded=1,
        summary=summary,
        quality_score=0.5,
        quality_rationale="常规。",
        markdown=summary,
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def test_root_property_reports_memory_under_cwd_by_default(tmp_path, monkeypatch) -> None:
    """缺省根是启动目录下的 `memory/`——`root` 属性如实报告（monkeypatch.chdir 模拟换启动目录）。"""

    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    capability = MemoryCapability(DeterministicEmbedder(), OverlapReranker())

    # Assert
    assert capability.root == tmp_path / "memory"


def test_tool_defaults_put_each_family_under_the_shared_root(tmp_path, monkeypatch) -> None:
    """四族共用一个记忆根，各占其下 `<kind>/`——只有一个开关管四族（原 104）。"""

    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    MemoryCapability(DeterministicEmbedder(), OverlapReranker())

    # Assert
    for kind in _KINDS:
        assert (tmp_path / "memory" / kind).is_dir(), kind


def test_explicit_memory_root_wins_over_the_default(tmp_path) -> None:
    """显式给 `memory_root` 时全部记忆族落在它下面（缺省不被用到）（原 119）。"""

    # Act
    MemoryCapability(DeterministicEmbedder(), OverlapReranker(), memory_root=tmp_path)

    # Assert
    for kind in _KINDS:
        assert (tmp_path / kind).is_dir(), kind


def test_restore_refreshes_every_family_not_just_step_memory(tmp_path) -> None:
    """restore 之后各记忆族的内存态都重读——快照后新写的记录不该从旧缓存里冒出来（原 238）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "act", "payload": _act(step=1)},
            {"kind": "task", "payload": _task()},
            {"kind": "episode", "payload": _episode("r1-ep1")},
            {"kind": "knowledge", "payload": _knowledge()},
            {"kind": "run", "payload": _run("run one")},
        ]
    )
    archive = capability.snapshot("s1")

    # 快照之后：每族再写一条（若 restore 不刷某族的内存态，这些会从旧缓存冒出来）
    capability.memorize(
        [
            {"kind": "act", "payload": _act(step=2)},
            {"kind": "task", "payload": _task()},
            {"kind": "episode", "payload": _episode("r1-ep2")},
            {"kind": "knowledge", "payload": _knowledge(text="草丛里可能有稀有宝可梦。")},
            {"kind": "run", "payload": _run("run two")},
        ]
    )

    # Act
    capability.restore(archive)

    # Assert
    assert [
        item["payload"]["step"]
        for item in capability.recall("", {"episode_id": _EP})
        if item["kind"] == "act"
    ] == [1]
    assert [
        item["payload"]["task_id"]
        for item in capability.recall("", {"episode_id": _EP})
        if item["kind"] == "task"
    ] == ["t1"]
    episode_ids = [
        item["payload"]["episode_id"]
        for item in capability.recall("", {"run_id": _RUN})
        if item["kind"] == "episode"
    ]
    assert episode_ids == ["r1-ep1"], f"episode 族的内存态也要跟着刷，实为 {episode_ids}"
    assert len([item for item in capability.recall("草丛", {}) if item["kind"] == "knowledge"]) == 1
    assert [item["payload"]["summary"] for item in capability.recall("", {"runs": "all"})] == [
        "run one"
    ]
