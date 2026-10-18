"""假检索 provider 下的 run 落盘、等值召回和整库恢复。"""

import zipfile
from pathlib import Path

import pytest

from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]


class _FakeReranker:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0] * len(documents)


def _capability(root: Path) -> MemoryCapability:
    return MemoryCapability(_FakeEmbedder(), _FakeReranker(), root)


def _run(run_id: str = "r1") -> RunMemory:
    return RunMemory(
        run_id=run_id,
        run_goal="通关 道馆｜目标",
        episodes=3,
        succeeded=2,
        summary="完成两局。",
        markdown="# 运行总结\n完成两局。",
        quality_score=0.5,
        quality_rationale="示例",
    )


def _episode(run_id: str, episode_id: str, run_goal: str) -> EpisodeMemory:
    return EpisodeMemory(
        run_id=run_id,
        episode_id=episode_id,
        run_goal=run_goal,
        goal="走到门口",
        steps=1,
        summary="到了。",
        markdown="到了。",
        quality_score=0.5,
        quality_rationale="示例",
    )


def test_run_memory_round_trips_through_memorize_and_recall(tmp_path: Path) -> None:
    capability = _capability(tmp_path)
    memory = _run()

    stored = capability.memorize([{"kind": "run", "payload": memory.model_dump()}])
    items = _capability(tmp_path).recall("", {"runs": "all"}, limit=8)

    assert len(items) == 1
    assert items[0]["uuid"] == stored[0]["uuid"]
    assert items[0]["kind"] == "run"
    assert items[0]["score"] is None
    assert items[0]["content"] == memory.markdown
    assert items[0]["payload"] == memory.model_dump(exclude={"markdown"})


def test_recall_by_run_goal_returns_only_matching_episodes_across_runs(tmp_path: Path) -> None:
    capability = _capability(tmp_path)
    episodes = [
        _episode("r10", "e2", "目标"),
        _episode("r2", "e10", "目标"),
        _episode("r2", "e2", "目标"),
        _episode("r1", "e1", "其他"),
    ]
    capability.memorize(
        [{"kind": "episode", "payload": memory.model_dump()} for memory in episodes]
    )

    items = capability.recall("", {"run_goal": "目标"}, limit=100)

    assert [(item["payload"]["run_id"], item["payload"]["episode_id"]) for item in items] == [
        ("r2", "e2"),
        ("r2", "e10"),
        ("r10", "e2"),
    ]
    assert all(item["kind"] == "episode" for item in items)


@pytest.mark.parametrize("goal", ["通关 第一个 道馆", "目标｜中文 空格", " goal "])
def test_run_goal_with_spaces_and_cjk_matches_by_equality(tmp_path: Path, goal: str) -> None:
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "episode", "payload": _episode("r1", "e1", goal).model_dump()},
            {"kind": "episode", "payload": _episode("r2", "e2", goal + "别的").model_dump()},
        ]
    )

    items = _capability(tmp_path).recall("", {"run_goal": goal}, limit=8)

    assert len(items) == 1
    assert items[0]["payload"]["run_goal"] == goal


def test_recall_runs_hint_lists_every_run_memory_and_no_episode(tmp_path: Path) -> None:
    capability = _capability(tmp_path)
    capability.memorize(
        [{"kind": "run", "payload": _run(run_id).model_dump()} for run_id in ("r10", "r2", "r1")]
    )
    capability.memorize([{"kind": "episode", "payload": _episode("r1", "e1", "目标").model_dump()}])

    items = capability.recall("", {"runs": "all"}, limit=100)

    assert [item["payload"]["run_id"] for item in items] == ["r1", "r2", "r10"]
    assert all(item["kind"] == "run" for item in items)


def test_restore_reloads_the_run_memory_family(tmp_path: Path) -> None:
    capability = _capability(tmp_path)
    writer = _capability(tmp_path / "source")
    writer.memorize([{"kind": "run", "payload": _run("r1").model_dump()}])
    archive = writer.snapshot("before")
    capability.memorize([{"kind": "run", "payload": _run("r2").model_dump()}])

    capability.restore(archive)
    items = capability.recall("", {"runs": "all"}, limit=8)

    assert [item["payload"]["run_id"] for item in items] == ["r1"]


def test_restore_with_an_empty_archive_clears_run_memory(tmp_path: Path) -> None:
    capability = _capability(tmp_path)
    capability.memorize(
        [
            {"kind": "run", "payload": _run().model_dump()},
            {"kind": "episode", "payload": _episode("r1", "e1", "目标").model_dump()},
        ]
    )
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass

    capability.restore(archive)

    for conditions in (
        {"runs": "all"},
        {"run_id": "r1"},
        {"run_goal": "目标"},
        {"episode_id": "e1"},
        {},
    ):
        assert capability.recall("", conditions, limit=8) == []
