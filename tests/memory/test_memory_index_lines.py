"""三级记忆索引的用法示范：有索引读结构化字段，空章渲染无正文。"""

import pytest
from _harness_fixtures.prompt_text import index_text, record_text

from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory, TaskMemory


def _episode(**changes: object) -> EpisodeMemory:
    values = dict(
        episode_id="r1-ep2",
        run_id="r1",
        goal="走到门口并进去",
        termination="goal_done",
        steps=3,
        acts_used=17,
        summary="从野外绕到门口后进入室内。之后又在室内走了几步。",
        quality_score=0.5,
        quality_rationale="示例",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    values.update(changes)
    return EpisodeMemory.model_validate(values)


def _task(**changes: object) -> TaskMemory:
    values = dict(
        task_id="r1-ep2-t1",
        run_id="r1",
        episode_id="r1-ep2",
        goal="走到门口",
        termination="goal_done",
        steps_used=5,
        total_acts=0,
        summary="走到了门口。后来又转身。",
        quality_score=0.5,
        quality_rationale="示例",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    values.update(changes)
    return TaskMemory.model_validate(values)


def _run(**changes: object) -> RunMemory:
    values = dict(
        run_id="r1",
        run_goal="通关第一个道馆",
        episodes=3,
        succeeded=2,
        termination="goal_done",
        summary="三局里两局成功。第三局卡在迷宫。",
        quality_score=0.5,
        quality_rationale="示例",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    values.update(changes)
    return RunMemory.model_validate(values)


@pytest.mark.parametrize(
    "factory,prefix",
    [
        (_episode, "- r1-ep2｜走到门口并进去｜成功｜goal_done｜3 task/17 键｜"),
        (_task, "- r1-ep2-t1｜走到门口｜成功｜goal_done｜5 键｜"),
        (_run, "- r1｜通关第一个道馆｜2/3 局成功｜goal_done｜"),
    ],
)
def test_index_reads_structured_index_and_source_status(factory, prefix: str) -> None:
    memory = factory(index={"headline": "进入室内", "keys": ["门口"], "evidence": ["换图"]})

    result = index_text(memory)

    assert result == prefix + "进入室内（keys：门口；含：换图）"
    stalled = index_text(factory(termination="stalled", index=memory.index))
    assert "｜stalled｜" in stalled
    if factory is not _run:
        assert "｜未成功｜" in stalled
    assert index_text(factory()).endswith("｜（无正文）")


def test_episode_render_never_prints_frames() -> None:
    memory = _episode(
        first_frame="data:image/png;base64,FIRST", last_frame="data:image/png;base64,LAST"
    )

    result = record_text(memory)

    assert "data:image" not in result
    assert "FIRST" not in result
    assert "LAST" not in result
