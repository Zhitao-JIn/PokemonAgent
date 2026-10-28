"""capability 的 memorize：各族落族、metadata 拼装、判重与前置断言。

只经 `MemoryCapability` 公开方法（D1）：写入走 `memorize`、校验走 `recall` 取回，
不读盘、不碰 store 私有成员。`MemoryCapability(embedder, reranker, memory_root=tmp_path)`
是唯一装配（D2，与 `build.py` 同形）。
"""

from __future__ import annotations

import pytest
from _doubles.memory import DeterministicEmbedder, OverlapReranker

from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory

_RUN = "r1"
_EP = "e1"


def _capability(tmp_path) -> MemoryCapability:
    return MemoryCapability(DeterministicEmbedder(), OverlapReranker(), memory_root=tmp_path)


def _act(step: int = 1, episode_id: str = _EP) -> dict:
    place = ActMemory.Observation.Place(map_id=12, x=13, y=8)
    obs = ActMemory.Observation(facts={"overlay": "none"}, step=step, place=place)
    return ActMemory(
        before=obs,
        action="up",
        after=obs,
        step=step,
        episode_id=episode_id,
        run_id=_RUN,
        observations=[],
        outcome=None,
    ).model_dump()


def _task(task_id: str = "t1", episode_id: str = _EP) -> dict:
    return TaskMemory(
        run_id=_RUN,
        episode_id=episode_id,
        task_id=task_id,
        goal="走到草丛",
        termination="goal_done",
        reason="到达",
        steps_used=3,
        total_acts=3,
        summary="沿空地向北走到草丛边。",
        quality_score=0.5,
        quality_rationale="常规移动。",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _episode(episode_id: str = "r1-ep1", markdown: str = "", summary: str = "") -> dict:
    return EpisodeMemory(
        episode_id=episode_id,
        run_id=_RUN,
        goal="g",
        steps=1,
        summary=summary,
        quality_score=0.0,
        quality_rationale="-",
        markdown=markdown,
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    ).model_dump()


def _knowledge(topic: str = "草丛", text: str = "草丛里会遇到野生宝可梦。") -> dict:
    return {
        "topic": topic,
        "text": text,
        "source": f"{_RUN}/{_EP}",
        "run_id": _RUN,
        "episode_id": _EP,
    }


def test_memorize_act_stores_run_episode_step_and_map_metadata(tmp_path) -> None:
    """act 的 metadata 含 run_id、episode_id、step、map_id（经 recall 取回校验，不读盘）。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act
    capability.memorize([{"kind": "act", "payload": _act(step=3)}])

    # Assert
    items = capability.recall("", {"episode_id": _EP})
    payload = items[0]["payload"]
    assert payload["run_id"] == _RUN
    assert payload["episode_id"] == _EP
    assert payload["step"] == 3
    assert payload["before"]["place"]["map_id"] == 12


def test_memorize_act_accepts_equal_step_and_rejects_lower_step(tmp_path) -> None:
    """act 的 step 单调：同 step 通过；更小 step 触发断言（缓存 miss 从索引现查的场景）。

    同实例内 `_check_step_monotonic` 的 max 缓存 miss 时填的是**写入前**的最大值、
    写入后不更新——所以"更小 step 被拦"这一幕发生在缓存可信的场景：新实例
    （= 进程重启）对同一 root 再写。这正是 harness 依赖的性质：episode 内 step
    单调跨重启也要成立。
    """

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=2)}])

    # Act / Assert
    capability.memorize([{"kind": "act", "payload": _act(step=2)}])
    restarted = _capability(tmp_path)
    with pytest.raises(AssertionError):
        restarted.memorize([{"kind": "act", "payload": _act(step=1)}])


def test_memorize_act_rejects_lower_step_in_same_instance(tmp_path) -> None:
    """O6 回归：同一实例内先写 step 6 再写 step 3 → 断言，且盘上只留下 step 6 那条。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=6)}])

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.memorize([{"kind": "act", "payload": _act(step=3)}])
    items = capability.recall("", {"episode_id": _EP})
    assert [item["payload"]["step"] for item in items] == [6]


def test_memorize_act_accepts_equal_step_in_same_instance(tmp_path) -> None:
    """同一实例内相等 step 仍然通过（单调是"不小于"，不是"大于"）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act(step=6)}])

    # Act
    stored = capability.memorize([{"kind": "act", "payload": _act(step=6)}])

    # Assert
    assert [entry["kind"] for entry in stored] == ["act"]


def test_memorize_task_stores_summary_as_searchable_text(tmp_path) -> None:
    """task 的 text = summary，可经 recall(episode_id=…) 取回 content == summary。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act
    capability.memorize([{"kind": "task", "payload": _task()}])

    # Assert
    items = [item for item in capability.recall("", {"episode_id": _EP}) if item["kind"] == "task"]
    assert items[0]["content"] == "沿空地向北走到草丛边。"


def test_memorize_episode_rejects_markdown_without_summary(tmp_path) -> None:
    """markdown 非空、summary 为空 → 断言（正文要么完整要么全空）。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.memorize([{"kind": "episode", "payload": _episode(markdown="有正文")}])


def test_memorize_episode_rejects_summary_without_markdown(tmp_path) -> None:
    """反向：summary 非空、markdown 为空 → 断言。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.memorize([{"kind": "episode", "payload": _episode(summary="有摘要")}])


def test_memorize_episode_accepts_both_empty(tmp_path) -> None:
    """两者皆空（空章）→ 通过，stored 含该条。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act
    stored = capability.memorize([{"kind": "episode", "payload": _episode()}])

    # Assert
    assert [entry["kind"] for entry in stored] == ["episode"]


def test_memorize_knowledge_skips_identical_topic_and_text(tmp_path) -> None:
    """knowledge 判重：第二次同 topic+text → stored 为空（探针已确认）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "knowledge", "payload": _knowledge()}])

    # Act
    stored = capability.memorize([{"kind": "knowledge", "payload": _knowledge()}])

    # Assert
    assert stored == []


def test_memorize_knowledge_keeps_same_topic_with_different_text(tmp_path) -> None:
    """同 topic 不同正文 → 两条都入库（判重按 topic+正文逐字）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "knowledge", "payload": _knowledge()}])

    # Act
    stored = capability.memorize(
        [{"kind": "knowledge", "payload": _knowledge(text="草丛里可能有稀有宝可梦。")}]
    )

    # Assert
    assert len(stored) == 1


def test_memorize_rejects_unknown_kind(tmp_path) -> None:
    """未知 kind → 断言（五族之外没有落盘点）。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.memorize([{"kind": "bogus", "payload": {}}])


def test_memorize_returns_stored_entries_with_kind_and_uuid(tmp_path) -> None:
    """stored 每条含 kind 与 uuid（真落库的才有；被判重跳过的不在其中）。"""

    # Arrange
    capability = _capability(tmp_path)

    # Act
    stored = capability.memorize(
        [
            {"kind": "act", "payload": _act()},
            {"kind": "knowledge", "payload": _knowledge()},
        ]
    )

    # Assert
    assert [entry["kind"] for entry in stored] == ["act", "knowledge"]
    assert all(entry["uuid"] for entry in stored)
