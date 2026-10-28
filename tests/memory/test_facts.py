"""Facts use episode-global and script-local coordinates independently."""

from pokemon_agent.memory.facts import task_facts, task_step_range
from pokemon_agent.schemas.memory import ActMemory


def _observation(step: int, scene: str, dialog: str = "") -> ActMemory.Observation:
    return ActMemory.Observation.model_validate(
        {
            "step": step,
            "place": {"map_id": 7, "x": 3, "y": 4},
            "scene": scene,
            "facts": {"scene": scene, "dialog_text": dialog},
            "settled": True,
        }
    )


def _step(step: int, scene: str, dialog: str = "") -> ActMemory.Observation.StepObs:
    return ActMemory.Observation.StepObs.model_validate(
        {
            "step": step,
            "place": {"map_id": 7, "x": 3, "y": 4},
            "facing": "north",
            "scene": scene,
            "overlay": "none",
            "dialog_text": dialog,
        }
    )


def test_fact_coordinates_separate_episode_step_from_script_substep() -> None:
    entry = ActMemory(
        before=_observation(37, "walk"),
        action="script:advance_dialog",
        after=_observation(38, "battle"),
        step=37,
        episode_id="episode-1",
        task_id="task-1",
        observations=[_step(1, "dialog", "你好"), _step(2, "dialog", "你好\n欢迎")],
        outcome=None,
    )

    facts = task_facts([entry], "task-1", "episode-1")

    dialog = [fact for fact in facts if fact.kind == "dialog_line"]
    assert [(fact.step, fact.sub, fact.text) for fact in dialog] == [
        (38, 1, "你好"),
        (38, 2, "欢迎"),
    ]
    assert task_step_range([entry]) == ["37-38"]
    assert all(fact.task_id == "task-1" and fact.episode_id == "episode-1" for fact in facts)


def test_key_action_boundary_fact_uses_substep_zero() -> None:
    entry = ActMemory(
        before=_observation(37, "walk"),
        action="up",
        after=_observation(38, "town"),
        step=37,
        episode_id="episode-1",
        task_id="task-1",
        observations=[],
        outcome=None,
    )

    facts = task_facts([entry], "task-1", "episode-1")

    assert facts and all((fact.step, fact.sub) == (38, 0) for fact in facts)
    assert task_step_range([entry]) == ["37-38"]
    assert task_step_range([]) == []
