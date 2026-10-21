"""首末帧只经三条门面的 images 通道发送，不调用模型或模拟器。"""

from collections.abc import Sequence

import pytest
from _harness_fixtures.brain import _Brain

from pokemon_agent.brain import Goal
from pokemon_agent.brain.interface import DecomposeResult, PlanResult, SummarizeRunResult
from pokemon_agent.direct.brain_tool import Decomposer, Planner, RunSummarizer, collect_frames
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolSummarizeRunReq,
)
from pokemon_agent.schemas.harness.domain import Termination
from pokemon_agent.schemas.memory import EpisodeMemory, TaskMemory
from pokemon_agent.world import TaskObservation, TaskScene


class _RecordingBrain(_Brain):
    def __init__(self) -> None:
        super().__init__(
            task=lambda asked: True,
            episode=lambda asked: True,
            run=lambda asked: True,
            tasks_per_plan=1,
        )
        self.frames: dict[str, list[str]] = {}
        self.prompts: dict[str, str] = {}

    def plan(
        self,
        *,
        prompt: str,
        goal_stack: Sequence[str],
        history: Sequence[str],
        max_push: int,
        images: Sequence[str] = (),
        thinking: bool | None = None,
    ) -> PlanResult:
        self.frames["plan"], self.prompts["plan"] = list(images), prompt
        return super().plan(
            prompt=prompt,
            goal_stack=goal_stack,
            history=history,
            max_push=max_push,
            images=images,
            thinking=thinking,
        )

    def decompose(
        self,
        *,
        prompt: str,
        goal: str,
        context: Sequence[str],
        max_tasks: int,
        images: Sequence[str] = (),
        thinking: bool | None = None,
    ) -> DecomposeResult:
        self.frames["decompose"], self.prompts["decompose"] = list(images), prompt
        return super().decompose(
            prompt=prompt,
            goal=goal,
            context=context,
            max_tasks=max_tasks,
            images=images,
            thinking=thinking,
        )

    def summarize_run(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        success: bool,
        steps: int,
        max_steps: int,
        images: Sequence[str] = (),
    ) -> SummarizeRunResult:
        self.frames["summarize_run"], self.prompts["summarize_run"] = list(images), prompt
        return super().summarize_run(
            prompt=prompt,
            goal=goal,
            history=history,
            success=success,
            steps=steps,
            max_steps=max_steps,
            images=images,
        )


def _episode(first: str | None, last: str | None, number: int = 0) -> EpisodeMemory:
    return EpisodeMemory(
        run_id="r",
        run_goal="总目标",
        episode_id=f"e{number}",
        goal="局目标",
        steps=2,
        summary="总结",
        quality_score=0.5,
        quality_rationale="q",
        first_frame=first,
        last_frame=last,
    )


def _task(first: str | None, last: str | None, number: int = 0) -> TaskMemory:
    return TaskMemory(
        run_id="r",
        episode_id="e",
        task_id=f"t{number}",
        goal="任务",
        steps_used=2,
        total_acts=number,
        summary="总结",
        quality_score=0.5,
        quality_rationale="q",
        first_frame=first,
        last_frame=last,
    )


def _invoke(
    brain: _RecordingBrain, method: str, episodes: list[EpisodeMemory], tasks: list[TaskMemory]
) -> None:
    if method == "plan":
        Planner(brain).plan(
            FromHarnessToBrainToolPlanOnceReq(
                run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
                run_id="r",
                plan=[],
                details=episodes,
                max_push=1,
            )
        )
    elif method == "decompose":
        Decomposer(brain).decompose(
            FromHarnessToBrainToolDecomposeReq(
                goal=Goal(goal="局目标", criteria="c"),
                observation=TaskObservation(step=0, status="s", scene=TaskScene.WALK),
                task_memories=tasks,
                max_tasks=1,
            )
        )
    else:
        RunSummarizer(brain).summarize_run(
            FromHarnessToBrainToolSummarizeRunReq(
                run_id="r",
                run_goal="总目标",
                goals=[],
                episode_memories=episodes,
                termination=Termination.GOAL_DONE,
                judge_reason="完成",
                episodes=len(episodes),
                succeeded=0,
                acts_used=2,
                max_episodes=20,
            )
        )


def test_collect_frames_dedups_by_string_and_keeps_first_occurrence() -> None:
    memories = [_episode("a", "b"), _task(None, "a"), _episode("c", "b")]

    frames = collect_frames(memories)

    assert frames == ["a", "b", "c"]
    assert memories[1].first_frame is None and memories[1].last_frame == "a"
    assert collect_frames([]) == []
    assert collect_frames([_task(None, None)]) == []


def test_plan_and_decompose_pass_images_to_the_brain() -> None:
    brain = _RecordingBrain()
    episodes = [_episode("a", "b"), _episode(None, "a", 1)]
    tasks = [_task("x", None), _task("y", "x", 1)]

    _invoke(brain, "plan", episodes, tasks)
    _invoke(brain, "decompose", episodes, tasks)

    assert brain.frames["plan"] == ["a", "b"]
    assert brain.frames["decompose"] == ["x", "y"]


def test_run_summarizer_passes_episode_frames_to_the_brain() -> None:
    brain = _RecordingBrain()
    episodes = [_episode(None, "a"), _episode("b", "a", 1)]

    _invoke(brain, "summarize_run", episodes, [])

    assert brain.frames["summarize_run"] == ["a", "b"]


@pytest.mark.parametrize("method", ["plan", "decompose", "summarize_run"])
def test_scope_images_are_capped_to_the_newest_twenty(method: str) -> None:
    brain = _RecordingBrain()
    frames = [f"frame-{index}" for index in range(24)]
    episodes = [_episode(frames[i], frames[i + 1], i) for i in range(0, 24, 2)]
    tasks = [_task(frames[i], frames[i + 1], i) for i in range(0, 24, 2)]

    _invoke(brain, method, episodes, tasks)

    assert brain.frames[method] == frames[-20:]


@pytest.mark.parametrize("method", ["plan", "decompose", "summarize_run"])
def test_frames_never_appear_in_the_plan_decompose_or_run_summary_prompts(method: str) -> None:
    brain = _RecordingBrain()
    frame = "data:image/png;base64,SECRET"

    _invoke(brain, method, [_episode(frame, frame)], [_task(frame, frame)])

    assert brain.frames[method] == [frame]
    assert "data:image" not in brain.prompts[method] and "SECRET" not in brain.prompts[method]
    assert "最后一张最新" in brain.prompts[method]


@pytest.mark.parametrize("method", ["plan", "decompose", "summarize_run"])
def test_memories_without_frames_keep_the_tool_call_text_only(method: str) -> None:
    brain = _RecordingBrain()

    _invoke(brain, method, [_episode(None, None)], [_task(None, None)])

    assert brain.frames[method] == []
