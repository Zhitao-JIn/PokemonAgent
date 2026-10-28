"""episode 派发 task 时，按执行序交出本局同目标的无帧背景。"""

from types import SimpleNamespace

from _harness_fixtures.app_config import DEFAULT_APP_CONFIG

from pokemon_agent.brain import Task
from pokemon_agent.harness.episode.act.dispatch_task import dispatch_task
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.task.task_entry import begin_task
from pokemon_agent.schemas.harness.domain import TaskEntry
from pokemon_agent.schemas.memory import TaskMemory


def _memory(task_id: str, order: int, goal: str = "去门口", episode: str = "e1") -> TaskMemory:
    return TaskMemory(
        run_id="r1",
        episode_id=episode,
        task_id=task_id,
        goal=goal,
        steps_used=2,
        total_acts=order,
        summary="到门口。后续略。",
        quality_score=0.5,
        quality_rationale="q",
        first_frame="FIRST",
        last_frame="LAST",
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _episode(memories: list[TaskMemory]) -> EpisodeRunState:
    return EpisodeRunState(
        run_id="r1",
        run_goal="总目标",
        episode_id="e1",
        goal=Task(task_id="ep", goal="局目标", success_criteria="c", max_steps=3),
        ep_ctx=EpisodeContext(task_memories=memories),
        tasks=[
            TaskEntry(
                entry_id=(
                    Task(task_id="current", goal="去门口", success_criteria="c", max_steps=12)
                ).task_id,
                round=1,
                task=Task(task_id="current", goal="去门口", success_criteria="c", max_steps=12),
            )
        ],
    )


def test_task_index_lists_prior_tasks_with_the_same_goal_in_this_episode_only() -> None:
    memories = [
        _memory("later", 8),
        _memory("other", 3, goal="另一目标"),
        _memory("earlier", 1),
        _memory("foreign", 0, episode="e2"),
    ]
    state = _episode(memories)

    task_input = dispatch_task(state)["task_input"]
    task = begin_task(
        SimpleNamespace(
            config=DEFAULT_APP_CONFIG,
            trace=SimpleNamespace(append=lambda req: None),
        ),
        task_input,
    )

    assert [memory.task_id for memory in task_input.task_index] == ["earlier", "later"]
    assert task.task_index == task_input.task_index
    assert all(
        memory.first_frame is None and memory.last_frame is None for memory in task.task_index
    )
    assert all(memory.first_frame == "FIRST" and memory.last_frame == "LAST" for memory in memories)
    assert all(memory.task_id != "current" for memory in task.task_index)


def test_task_index_is_empty_without_a_matching_prior_task() -> None:
    state = _episode([_memory("other", 0, goal="去 门口")])

    result = dispatch_task(state)

    assert result["task_input"].task_index == []


def test_new_execution_can_use_the_previous_same_goal_attempt_as_background() -> None:
    state = _episode([_memory("current", 0)])

    output = dispatch_task(state)
    assert output["task_input"].task.task_id != "current"
    assert output["task_input"].task_index[0].task_id == "current"
