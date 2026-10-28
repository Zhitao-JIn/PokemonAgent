"""New memory coordinates are required for every serialized record."""

import pytest
from pydantic import ValidationError

from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory, TaskMemory


def _act() -> ActMemory:
    observation = ActMemory.Observation(step=37)
    return ActMemory(
        before=observation,
        action="up",
        after=observation,
        step=37,
        episode_id="episode-1",
        observations=[],
        outcome=None,
    )


def _task() -> TaskMemory:
    return TaskMemory(
        run_id="run-1",
        episode_id="episode-1",
        task_id="task-1",
        goal="goal",
        steps_used=1,
        total_acts=37,
        summary="summary",
        quality_score=0.5,
        quality_rationale="reason",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _episode() -> EpisodeMemory:
    return EpisodeMemory(
        run_id="run-1",
        run_goal="run goal",
        episode_id="episode-1",
        goal="goal",
        steps=1,
        summary="summary",
        quality_score=0.5,
        quality_rationale="reason",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _run() -> RunMemory:
    return RunMemory(
        run_id="run-1",
        run_goal="run goal",
        episodes=1,
        succeeded=1,
        summary="summary",
        quality_score=0.5,
        quality_rationale="reason",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


@pytest.mark.parametrize(
    "factory,field",
    [
        (_act, "observations"),
        (_act, "outcome"),
        (_task, "facts"),
        (_task, "pointers"),
        (_task, "index"),
        (_episode, "pointers"),
        (_episode, "index"),
        (_run, "pointers"),
        (_run, "index"),
    ],
)
def test_serialized_memory_missing_a_new_field_is_rejected(factory, field: str) -> None:
    record = factory()
    payload = record.model_dump(mode="json")
    payload.pop(field)

    with pytest.raises(ValidationError):
        type(record).model_validate(payload)
