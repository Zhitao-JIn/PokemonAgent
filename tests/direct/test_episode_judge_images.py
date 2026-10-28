"""L1 判定取 task 首末帧并过帽，逐步历史与 L0 的现有图路径不变。"""

from collections.abc import Sequence

from _harness_fixtures.app_config import call_policy
from _harness_fixtures.brain import _Brain

from pokemon_agent.brain import Goal
from pokemon_agent.brain.interface import JudgeResult, ModelCall
from pokemon_agent.direct.brain_tool import Judger
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory


class _RecordingBrain(_Brain):
    def __init__(self) -> None:
        super().__init__(
            task=lambda asked: False,
            episode=lambda asked: False,
            run=lambda asked: False,
            tasks_per_plan=1,
        )
        self.frames: list[str] = []

    def judge(
        self, *, prompt: str, goal: str, history: Sequence[str], images: Sequence[str] = ()
    ) -> JudgeResult:
        self.frames = list(images)
        return JudgeResult(
            decision=("achieved" if False else "continue"),
            why="继续",
            calls=[ModelCall(payload={})],
        )


def _task(number: int, first: str | None, last: str | None) -> TaskMemory:
    return TaskMemory(
        run_id="r",
        episode_id="e",
        task_id=f"t{number}",
        goal="任务",
        steps_used=1,
        total_acts=number,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
        first_frame=first,
        last_frame=last,
        facts=[],
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _act(step: int, first: str, last: str) -> ActMemory:
    return ActMemory(
        episode_id="e",
        task_id="t",
        step=step,
        action="up",
        before=ActMemory.Observation(facts={"overlay": "none"}, step=step),
        after=ActMemory.Observation(facts={"overlay": "none"}, step=step + 1),
        before_frame=first,
        after_frame=last,
        observations=[],
        outcome=None,
    )


def test_judger_sends_capped_task_frames_when_history_is_empty() -> None:
    brain = _RecordingBrain()
    frames = [f"frame-{index}" for index in range(24)]
    tasks = [_task(i, frames[i], frames[i + 1]) for i in range(0, 24, 2)]
    tasks += [_task(24, None, frames[-1]), _task(25, None, None)]
    request = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal="局目标", criteria="c"), task_memories=tasks
    )

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert brain.frames == frames[-20:]


def test_judger_prefers_step_history_and_deduplicates_its_boundary_frames() -> None:
    brain = _RecordingBrain()
    request = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal="任务", criteria="c"),
        history=[_act(0, "a", "b"), _act(1, "b", "c")],
        task_memories=[_task(0, "task-first", "task-last")],
    )

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert brain.frames == ["a", "b", "c"]


def test_task_history_images_are_not_capped_even_when_there_are_more_than_twenty() -> None:
    brain = _RecordingBrain()
    frames = [f"frame-{index}" for index in range(24)]
    history = [_act(i, frames[2 * i], frames[2 * i + 1]) for i in range(12)]
    request = FromHarnessToBrainToolJudgeReq(goal=Goal(goal="任务", criteria="c"), history=history)

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert brain.frames == frames


def test_judger_sends_capped_episode_frames_when_history_is_empty() -> None:
    brain = _RecordingBrain()
    memory = EpisodeMemory(
        run_id="r",
        run_goal="g",
        episode_id="e",
        goal="局目标",
        steps=1,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
        first_frame="frame-0",
        last_frame="frame-1",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    frames = [f"frame-{index}" for index in range(24)]
    memories = [
        memory.model_copy(
            update={"episode_id": f"e{i}", "first_frame": frames[i], "last_frame": frames[i + 1]}
        )
        for i in range(0, 24, 2)
    ]
    memories.append(memory.model_copy(update={"first_frame": None, "last_frame": None}))
    request = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal="总目标", criteria="c"), episode_memories=memories
    )

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert brain.frames == frames[-20:]
