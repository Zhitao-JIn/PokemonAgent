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
    )
    values.update(changes)
    return RunMemory.model_validate(values)


@pytest.mark.parametrize(
    "factory,identifier",
    [
        (_episode, "r1-ep2"),
        (_task, "r1-ep2-t1"),
        (_run, "r1"),
    ],
)
def test_index_reads_structured_index_and_source_status(factory, identifier: str) -> None:
    memory = factory(index={"headline": "进入室内", "keys": ["门口"], "evidence": ["换图"]})

    result = index_text(memory)

    assert result.startswith(f"- {identifier}｜")
    assert result.endswith("进入室内（keys：门口；含：换图）")
    assert (
        "未成功" in index_text(factory(termination="stalled", index=memory.index))
        or factory is _run
    )
    assert "（keys：" not in index_text(factory())
    assert index_text(factory()).endswith("（无正文）")


def test_episode_render_never_prints_frames() -> None:
    memory = _episode(
        first_frame="data:image/png;base64,FIRST", last_frame="data:image/png;base64,LAST"
    )

    result = record_text(memory)

    assert "data:image" not in result
    assert "FIRST" not in result
    assert "LAST" not in result
