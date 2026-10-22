"""capability 的 recall：分族路由（act/task/object/episode 摘要/knowledge）与截断、limit 前置。

只经 `MemoryCapability.recall` 公开口；各族顺序（act step 升序 → task total_acts 升序、
episode 摘要自然序）是读口自己的约定，调用方不传排序参数。
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
        before=obs, action="up", after=obs, step=step, episode_id=episode_id, run_id=_RUN
    ).model_dump()


def _task(task_id: str = "t1", episode_id: str = _EP, total_acts: int = 1) -> dict:
    return TaskMemory(
        run_id=_RUN,
        episode_id=episode_id,
        task_id=task_id,
        goal="走到草丛",
        termination="goal_done",
        reason="到达",
        steps_used=3,
        total_acts=total_acts,
        summary=f"task {task_id} 的总结。",
        quality_score=0.5,
        quality_rationale="常规移动。",
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


def _object(step: int = 1, episode_id: str = _EP) -> dict:
    from pokemon_agent.schemas.memory.datastore.object_memory import ObjectDialogEvent

    place = ObjectDialogEvent.Place(map_id=12, x=13, y=8)
    return ObjectDialogEvent(
        outcome="dialog",
        episode_id=episode_id,
        step=step,
        run_id=_RUN,
        place=place,
        actor_place=place,
        object_kind="人",
        button="a",
        text="你好。",
    ).model_dump()


def test_recall_by_episode_id_returns_acts_in_step_order_then_tasks(tmp_path) -> None:
    """同局 recall：先 act（step 升序），后 task（total_acts 升序）——与写入顺序无关。

    task 族没有 append 单调约束，仍乱序写（t2 先于 t1、total_acts 5 先于 2），读回的
    total_acts 升序与写入序相反，排序验证保留；act/object 按 O6 修复后的契约升序写。
    """

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "task", "payload": _task("t2", total_acts=5)},
            {"kind": "act", "payload": _act(step=1)},
            {"kind": "task", "payload": _task("t1", total_acts=2)},
            {"kind": "act", "payload": _act(step=2)},
        ]
    )

    # Act
    items = capability.recall("", {"episode_id": _EP})

    # Assert
    kinds = [item["kind"] for item in items]
    assert kinds == ["act", "act", "task", "task"]
    assert [item["payload"]["step"] for item in items[:2]] == [1, 2]
    assert [item["payload"]["total_acts"] for item in items[2:]] == [2, 5]


def test_recall_by_place_or_map_id_routes_to_object_family(tmp_path) -> None:
    """conditions 带 place 或 map_id → object 族（step 升序；O6 修复后同实例须按序写）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "object", "payload": _object(step=1)},
            {"kind": "object", "payload": _object(step=2)},
            {"kind": "act", "payload": _act(step=1)},
        ]
    )

    # Act
    by_place = capability.recall("", {"place": "12:13:8"})
    by_map = capability.recall("", {"map_id": "12"})

    # Assert
    assert [item["kind"] for item in by_place] == ["object", "object"]
    assert [item["payload"]["step"] for item in by_place] == [1, 2]
    assert [item["kind"] for item in by_map] == ["object", "object"]


def test_recall_by_run_id_returns_episode_summaries_in_natural_order(tmp_path) -> None:
    """run_id → episode 摘要按 episode_id 自然序（r1-ep2 排在 r1-ep10 之前）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {
                "kind": "episode",
                "payload": _episode(f"r1-ep{n}", markdown=f"第 {n} 局。", summary=f"第 {n} 局。"),
            }
            for n in (10, 2, 12, 1, 11, 3)
        ]
    )

    # Act
    items = [item for item in capability.recall("", {"run_id": _RUN}) if item["kind"] == "episode"]

    # Assert
    assert [item["payload"]["episode_id"] for item in items] == [
        "r1-ep1",
        "r1-ep2",
        "r1-ep3",
        "r1-ep10",
        "r1-ep11",
        "r1-ep12",
    ]


def test_recall_with_query_returns_knowledge_with_score_none(tmp_path) -> None:
    """D4（O4 之后的行为）：knowledge 条目 score 恒为 None——本路不回填相关性分。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {
                "kind": "knowledge",
                "payload": {
                    "topic": "草丛",
                    "text": "草丛里会遇到野生宝可梦。",
                    "source": f"{_RUN}/{_EP}",
                    "run_id": _RUN,
                    "episode_id": _EP,
                },
            }
        ]
    )

    # Act
    items = [item for item in capability.recall("草丛", {}) if item["kind"] == "knowledge"]

    # Assert
    assert items, "应命中刚写入的知识"
    assert all(item["score"] is None for item in items)


def test_recall_with_no_hints_and_no_query_returns_empty(tmp_path) -> None:
    """无 hint 无 query：各族都不被圈中，返回空列表。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize([{"kind": "act", "payload": _act()}])

    # Act
    items = capability.recall("", {})

    # Assert
    assert items == []


def test_recall_truncates_to_limit(tmp_path) -> None:
    """多族合并后截断到 limit（hint 族在前，语义族随后）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "act", "payload": _act(step=1)},
            {"kind": "act", "payload": _act(step=2)},
            {"kind": "act", "payload": _act(step=3)},
        ]
    )

    # Act
    items = capability.recall("", {"episode_id": _EP}, limit=2)

    # Assert
    assert len(items) == 2


def test_recall_with_episode_query_and_zero_limit_raises_assertion(tmp_path) -> None:
    """D5：episode 分支 + query + limit=0 → AssertionError（rank 的 fuse_top_k 前置）。"""

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [{"kind": "episode", "payload": _episode("r1-ep1", markdown="一。", summary="一。")}]
    )

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.recall("草丛", {"episode_id": "r1-ep1"}, limit=0)


def test_recall_with_knowledge_query_and_zero_limit_raises_assertion(tmp_path) -> None:
    """D5：knowledge query + limit=0 → AssertionError。

    **经 episode 分支触发**（K1）：knowledge 分支自己不查 limit，断言来自
    `_recall_episode_summaries` 里 `store.rank(uuids, query, limit)` 的
    `fuse_top_k > 0` 前置——两层都会 AssertionError（store spec CP3 之后）。
    """

    # Arrange
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {
                "kind": "knowledge",
                "payload": {
                    "topic": "草丛",
                    "text": "草丛里会遇到野生宝可梦。",
                    "source": f"{_RUN}/{_EP}",
                    "run_id": _RUN,
                    "episode_id": _EP,
                },
            }
        ]
    )

    # Act / Assert
    with pytest.raises(AssertionError):
        capability.recall("草丛", {}, limit=0)
