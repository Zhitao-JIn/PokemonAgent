"""run 目标与本局首末 task 帧的来源章盖章。"""

from types import SimpleNamespace

from _harness_fixtures.brain import _Brain
from _harness_fixtures.memory import _Memory

from pokemon_agent.direct.brain_tool import Summarizer
from pokemon_agent.harness.episode.episode_done.leave_chapter import store_empty_chapter
from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeReq
from pokemon_agent.schemas.harness.domain import Termination
from pokemon_agent.schemas.memory import TaskMemory


def _task(index: int, first: str | None, last: str | None) -> TaskMemory:
    return TaskMemory(
        run_id="r1",
        episode_id="e1",
        task_id=f"t{index}",
        goal="局目标",
        steps_used=1,
        total_acts=index,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
        first_frame=first,
        last_frame=last,
    )


def test_episode_chapter_carries_run_goal_and_first_last_frames() -> None:
    summarizer = Summarizer(_Brain(lambda n: True, lambda n: True, lambda n: True, 1))
    req = FromHarnessToBrainToolSummarizeReq(
        run_id="r1",
        run_goal="总目标",
        episode_id="e1",
        goal="局目标",
        entries=[_task(0, "FIRST", "INNER"), _task(1, "INNER2", "LAST")],
        verdicts=[],
        termination=Termination.GOAL_DONE,
        steps=2,
        acts_used=2,
        max_steps=3,
    )

    memory = summarizer.summarize(req).episode_memory

    assert memory.run_goal == "总目标"
    assert (memory.first_frame, memory.last_frame) == ("FIRST", "LAST")
    req.entries[0].first_frame = None
    req.entries[-1].last_frame = None
    missing = summarizer.summarize(req).episode_memory
    assert missing.first_frame is None and missing.last_frame is None


def test_empty_chapter_carries_run_goal_and_no_frames() -> None:
    deps = SimpleNamespace(memory=_Memory(), trace=SimpleNamespace(append=lambda req: None))

    memory = store_empty_chapter(
        deps,
        run_id="r1",
        run_goal="总目标",
        episode_id="e1",
        goal="局目标",
        tasks_used=0,
        acts_used=0,
        termination=Termination.ERROR,
        reason="error",
        source="test",
        step=0,
    )

    assert memory.run_goal == "总目标"
    assert memory.first_frame is None and memory.last_frame is None
