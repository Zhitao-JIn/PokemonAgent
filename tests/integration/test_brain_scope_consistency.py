"""无存档三层图的范围契约：共享详情、隔离背景、图上限与一次 run 收尾。"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from _harness_fixtures.harness import GOAL, FakeRun, build_fake
from _harness_fixtures.prompt_text import index_text
from pydantic import BaseModel

from pokemon_agent.direct.trace import parse
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolSummarizeRunReq,
)
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, RunMemory, TaskMemory

RUN_GOAL = "依次完成：到达A"


@dataclass
class _Seen:
    request: BaseModel
    children: list[ActMemory | TaskMemory | EpisodeMemory]
    images: list[str]
    tasks: list[TaskMemory]
    episodes: list[EpisodeMemory]


@dataclass
class _Recording:
    requests: dict[str, list[_Seen]]
    calls: list[tuple[str, list[str]]]


def _seed_details(fake: FakeRun) -> None:
    """预置本 run 的局详情与两局的此前 task，含重复帧和不同目标。"""
    fake.memory.episodes.extend(
        EpisodeMemory(
            run_id="r1",
            run_goal=RUN_GOAL,
            goal_id=GOAL.task_id,
            episode_id=f"r1-ep{index + 1}",
            goal="旧局",
            steps=1,
            summary="首句。\n正文第二句。",
            quality_score=0.5,
            quality_rationale="固定样例",
            first_frame=f"frame-{index * 2}",
            last_frame=f"frame-{index * 2 + 1}",
            pointers=[],
            index={"headline": "", "keys": [], "evidence": []},
        )
        for index in range(12)
    )
    fake.memory.episodes.append(
        fake.memory.episodes[0].model_copy(update={"episode_id": "duplicate-frames"})
    )
    for episode_id in ("r1-ep1", "r1-ep2"):
        for goal in ("子任务", "另一目标"):
            fake.memory.tasks.append(
                TaskMemory(
                    run_id="r1",
                    episode_id=episode_id,
                    task_id=f"{episode_id}-old-{goal}",
                    goal=goal,
                    steps_used=1,
                    total_acts=0,
                    summary="旧任务。\n第二句。",
                    quality_score=0.5,
                    quality_rationale="固定样例",
                    first_frame="shared-frame",
                    last_frame="shared-frame",
                    facts=[],
                    pointers=[],
                    index={"headline": "", "keys": [], "evidence": []},
                )
            )


def _seed_indexes(fake: FakeRun) -> None:
    """索引候选来自别的 run；异目标的局与异局 task 不能进入对应背景。"""
    foreign = fake.memory.episodes[0].model_copy(
        update={"run_id": "past-run", "episode_id": "foreign-episode"}
    )
    fake.memory.episodes.extend(
        [foreign, foreign.model_copy(update={"episode_id": "other-goal", "run_goal": "别的目标"})]
    )
    fake.memory.runs.append(
        RunMemory(
            run_id="past-run",
            run_goal="另一总目标",
            episodes=1,
            succeeded=0,
            summary="过往 run。\n第二句。",
            quality_score=0.5,
            quality_rationale="固定样例",
            pointers=[],
            index={"headline": "", "keys": [], "evidence": []},
        )
    )
    fake.memory.tasks.append(
        fake.memory.tasks[0].model_copy(update={"episode_id": "foreign-episode"})
    )


def _record_brain(monkeypatch: pytest.MonkeyPatch, brain: object, recording: _Recording) -> None:
    """记录真实门面发给假 BrainPort 的方法与图片，不改变返回值。"""

    def wrap(method: Callable[..., Any], name: str) -> Callable[..., Any]:
        def call(**kwargs: Any) -> Any:
            recording.calls.append((name, list(kwargs.get("images", ()))))
            return method(**kwargs)

        return call

    for name in ("plan", "decompose", "choose", "judge", "verify", "summarize", "summarize_run"):
        monkeypatch.setattr(brain, name, wrap(getattr(brain, name), name))


def _record_requests(monkeypatch: pytest.MonkeyPatch, fake: FakeRun, recording: _Recording) -> None:
    """在各 Port 边界保留请求原对象与当时的完整子记忆快照。"""

    def wrap(method: Callable[..., Any], name: str, family: str) -> Callable[..., Any]:
        def call(request: BaseModel) -> Any:
            children = list(getattr(fake.memory, family))
            start = len(recording.calls)
            response = method(request)
            calls = recording.calls[start:]
            assert len(calls) == 1
            recording.requests.setdefault(name, []).append(
                _Seen(
                    request,
                    children,
                    calls[0][1],
                    list(fake.memory.tasks),
                    list(fake.memory.episodes),
                )
            )
            return response

        return call

    episode = fake.run_rt.episode
    for capability, method, name, family in (
        (fake.run_rt.planner, "plan", "L0.plan", "episodes"),
        (fake.run_rt.judger, "judge", "L0.judge", "episodes"),
        (episode.decomposer, "decompose", "L1.plan", "tasks"),
        (episode.judger, "judge", "L1.judge", "tasks"),
        (episode.task.chooser, "choose", "L2.plan", "acts"),
        (episode.task.judger, "judge", "L2.judge", "acts"),
        (fake.run_rt.run_summarizer, "summarize_run", "run.summary", "episodes"),
    ):
        monkeypatch.setattr(capability, method, wrap(getattr(capability, method), name, family))


def _details(request: BaseModel) -> Sequence[ActMemory | TaskMemory | EpisodeMemory]:
    """各层的规划与判定只比较各自的详情通道。"""
    if isinstance(request, FromHarnessToBrainToolPlanOnceReq):
        return request.details
    if isinstance(request, FromHarnessToBrainToolDecomposeReq):
        return request.task_memories
    if isinstance(request, FromHarnessToBrainToolChooseOnceReq):
        return request.memories
    assert isinstance(request, FromHarnessToBrainToolJudgeReq)
    return request.history or request.task_memories or request.episode_memories


def _assert_shared_details(recording: _Recording) -> None:
    """验收 1：每层非空详情完整，继续规划的圈与本圈判定共享原列表。"""
    for layer, identity in (("L0", "run_id"), ("L1", "episode_id"), ("L2", "task_id")):
        plans = [seen for seen in recording.requests[f"{layer}.plan"] if _details(seen.request)]
        judges = recording.requests[f"{layer}.judge"]
        assert plans, f"{layer} requires a nonempty planning round"
        for seen in [*plans, *judges]:
            details = _details(seen.request)
            assert details
            unit = getattr(details[0], identity)
            expected = [memory for memory in seen.children if getattr(memory, identity) == unit]
            assert len(details) == len(expected)
            assert list(details) == expected
        paired = 0
        for plan in plans:
            candidates = [
                judge for judge in judges if _details(plan.request) == _details(judge.request)
            ]
            if candidates:
                paired += 1
                assert any(
                    _details(plan.request) is _details(judge.request) for judge in candidates
                )
        assert paired, f"{layer} requires a continuing round with both plan and judge"


def _assert_indexes(recording: _Recording, seeded: bool, episode_goals: dict[str, str]) -> None:
    """验收 2：背景排除本单元，task 背景只取同局同目标的此前 task。"""
    for name in ("L0.plan", "L0.judge", "L1.plan", "L1.judge", "L2.plan", "L2.judge"):
        for seen in recording.requests[name]:
            request = seen.request
            if name.startswith("L0"):
                index = request.run_index
                assert {memory.run_id for memory in index} == ({"past-run"} if seeded else set())
                assert all(memory.run_id != "r1" for memory in index)
            elif name.startswith("L1"):
                episode_id = request.task_memories[0].episode_id
                goal_id = episode_goals[episode_id]
                index = request.episode_index
                assert {memory.episode_id for memory in index} == {
                    memory.episode_id
                    for memory in seen.episodes
                    if memory.run_id == "r1"
                    and memory.goal_id == goal_id
                    and memory.episode_id != episode_id
                }
                assert all(memory.episode_id != episode_id for memory in index)
                assert all(memory.run_id == "r1" and memory.goal_id == goal_id for memory in index)
                assert "foreign-episode" not in {memory.episode_id for memory in index}
            else:
                index = request.task_index
                assert index
                episode_id = index[0].episode_id
                expected = [
                    memory.model_copy(update={"first_frame": None, "last_frame": None})
                    for memory in seen.tasks
                    if memory.episode_id == episode_id and memory.goal == "子任务"
                ]
                assert list(index) == sorted(expected, key=lambda memory: memory.total_acts)
                assert all(
                    memory.episode_id == episode_id and memory.goal == "子任务" for memory in index
                )
                if _details(request):
                    assert all(memory.task_id != _details(request)[0].task_id for memory in index)
            assert all(
                "\n" not in index_text(memory) and "\r" not in index_text(memory)
                for memory in index
            )


def _assert_images(recording: _Recording) -> None:
    """验收 6：实际带图调用不过帽，L0/L1/run 蒸馏按字符串去重并保留最新帧。"""
    assert all(
        len(images) <= DEFAULT_APP_CONFIG.memory.scope_image_cap for _, images in recording.calls
    )
    for name in ("L0.plan", "L0.judge", "L1.plan", "L1.judge", "run.summary"):
        duplicated = False
        for seen in recording.requests[name]:
            request = seen.request
            memories = (
                request.episode_memories
                if isinstance(request, FromHarnessToBrainToolSummarizeRunReq)
                else _details(request)
            )
            frames = [
                frame
                for memory in memories
                for frame in (memory.first_frame, memory.last_frame)
                if frame is not None
            ]
            unique = list(dict.fromkeys(frames))
            duplicated |= len(unique) < len(frames)
            assert seen.images == unique[-DEFAULT_APP_CONFIG.memory.scope_image_cap :]
        assert duplicated, f"{name} must exercise duplicate frames"
    assert any(
        len(_details(seen.request)) * 2 > DEFAULT_APP_CONFIG.memory.scope_image_cap
        for seen in recording.requests["L0.judge"]
    )


def test_brain_scope_consistency_across_three_graphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recordings: list[_Recording] = []

    for seeded in (False, True):
        fake = build_fake(tmp_path / str(seeded), checkpoints=False, tasks_per_plan=1)
        _seed_details(fake)
        if seeded:
            _seed_indexes(fake)
        recording = _Recording({}, [])
        _record_brain(monkeypatch, fake.run_rt.planner._brain, recording)
        _record_requests(monkeypatch, fake, recording)

        result = fake.harness.run("r1", [GOAL])

        _assert_shared_details(recording)
        episode_goals = {
            event.meta.episode_id: event.content.goal_id
            for raw in fake.run_rt.trace.read_events()
            if (event := parse(raw)).kind == "episode_start"
        }
        _assert_indexes(recording, seeded, episode_goals)
        _assert_images(recording)
        assert Counter(name for name, _ in recording.calls)["summarize_run"] == 1
        memories = [memory for memory in fake.memory.runs if memory.run_id == "r1"]
        assert len(memories) == 1
        assert memories[0].termination == result.termination
        assert memories[0].success and result.termination == "goal_done"
        recordings.append(recording)

    assert Counter(name for name, _ in recordings[0].calls) == Counter(
        name for name, _ in recordings[1].calls
    )
