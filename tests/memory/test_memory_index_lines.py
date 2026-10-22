"""三级记忆索引及旧 payload 的用法示范。"""

from collections.abc import Callable

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


def test_episode_index_line_matches_fixed_sample() -> None:
    memory = _episode()

    result = index_text(memory)

    assert (
        result
        == "- r1-ep2｜走到门口并进去｜成功｜goal_done｜3 task/17 键｜从野外绕到门口后进入室内。"
    )


def test_task_index_line_matches_fixed_sample() -> None:
    memory = _task()

    result = index_text(memory)

    assert result == "- r1-ep2-t1｜走到门口｜成功｜goal_done｜5 键｜走到了门口。"


def test_run_index_line_matches_fixed_sample() -> None:
    memory = _run()

    result = index_text(memory)

    assert result == "- r1｜通关第一个道馆｜2/3 局成功｜goal_done｜三局里两局成功。"


@pytest.mark.parametrize(
    "text, expected",
    [
        *(("  首句" + mark + "后文  ", "首句" + mark) for mark in "。！？.!?"),
        ("首句\n后文", "首句"),
        ("首句\r\n后文", "首句"),
        ("字" * 80, "字" * 80),
        ("字" * 81 + "。", "字" * 80 + "…"),
        ("3.14", "3."),
        ("  ", "（无正文）"),
    ],
)
def test_first_sentence_stops_at_terminator_and_truncates_at_eighty_chars(
    text: str, expected: str
) -> None:
    result = index_text(_episode(summary=text)).split("｜")[-1]

    assert result == expected


@pytest.mark.parametrize("factory", [_episode, _task, _run])
def test_empty_summary_index_line_says_no_body(
    factory: Callable[..., EpisodeMemory | TaskMemory | RunMemory],
) -> None:
    memory = factory(summary="  ")

    result = index_text(memory)

    assert result.endswith("｜（无正文）")


@pytest.mark.parametrize("factory", [_episode, _task, _run])
def test_index_line_writes_dash_when_termination_is_empty(
    factory: Callable[..., EpisodeMemory | TaskMemory | RunMemory],
) -> None:
    memory = factory(termination="")

    result = index_text(memory)

    assert "｜-｜" in result
    assert not memory.success


def test_episode_memory_reads_old_payload_without_new_fields() -> None:
    payload = _episode().model_dump(exclude={"run_goal", "first_frame", "last_frame"})

    memory = EpisodeMemory.model_validate(payload)

    assert memory.run_goal == ""
    assert memory.first_frame is None
    assert memory.last_frame is None


def test_episode_render_never_prints_frames() -> None:
    memory = _episode(
        first_frame="data:image/png;base64,FIRST", last_frame="data:image/png;base64,LAST"
    )

    result = record_text(memory)

    assert "data:image" not in result
    assert "FIRST" not in result
    assert "LAST" not in result
