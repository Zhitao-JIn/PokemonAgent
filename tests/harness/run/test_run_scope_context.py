"""run 感知的详情、跨目标背景与每圈知识检索，不运行整图。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from _harness_fixtures.memory import _Memory
from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.harness.episode.perceive.retrieve_knowledge_semantic_memory import (
    build_knowledge_query as episode_query,
)
from pokemon_agent.harness.knowledge_query import build_knowledge_query
from pokemon_agent.harness.run.perceive import perceive
from pokemon_agent.harness.run.perceive.read_plan_context import read_plan_context
from pokemon_agent.harness.run.perceive.retrieve_run_knowledge import retrieve_run_knowledge
from pokemon_agent.harness.run.run_state import PlanContext, RunState
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
)
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory
from pokemon_agent.world import Facts, TaskObservation, TaskScene


class _RecordingMemory(_Memory):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[FromHarnessToMemoryToolRecallReq] = []
        self.knowledge_queries = 0

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        self.requests.append(req)
        if req.query:
            self.knowledge_queries += 1
            return FromHarnessToMemoryToolRecallResp(
                items=[
                    FromHarnessToMemoryToolRecallItem(
                        kind="knowledge",
                        uuid="k",
                        content=f"知识{self.knowledge_queries}",
                        payload={"source": "guide.md"},
                    ),
                    FromHarnessToMemoryToolRecallItem(
                        kind="run", uuid="ignore", content="不该成为知识", payload={}
                    ),
                ]
            )
        response = super().recall(req)
        if req.conditions == {"runs": "all"}:
            other = FromHarnessToMemoryToolRecallItem(kind="knowledge", uuid="ignore", payload={})
            return response.model_copy(update={"items": [*response.items, other]})
        return response


def _episode(run: str, episode: str) -> EpisodeMemory:
    return EpisodeMemory(
        run_id=run,
        run_goal="g",
        episode_id=episode,
        goal="局目标",
        steps=1,
        termination="goal_done",
        summary=episode,
        quality_score=0.5,
        quality_rationale="q",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _run(run: str, goal: str) -> RunMemory:
    return RunMemory(
        run_id=run,
        run_goal=goal,
        episodes=1,
        succeeded=1,
        summary="背景首句。背景正文。",
        quality_score=0.5,
        quality_rationale="q",
        markdown="复盘正文",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )


def _state() -> RunState:
    observation = TaskObservation(
        step=0,
        scene=TaskScene.WALK,
        place={"map_id": 12, "x": 3, "y": 5},
        facts=Facts(overlay="none"),
    )
    return RunState(
        run_id="r1",
        run_goal=Goal(goal="总目标 中文", criteria="c"),
        goals=[],
        observation=observation,
    )


def _runtime(root: Path, memory: _RecordingMemory) -> Runtime:
    return Runtime(
        context=SimpleNamespace(
            config=DEFAULT_APP_CONFIG,
            memory=memory,
            trace=TraceTool.build(run_id="r1", trace_root=root),
        )
    )


def test_run_index_excludes_current_run_and_ignores_run_goal(tmp_path: Path) -> None:
    state, memory = _state(), _RecordingMemory()
    memory.episodes = [
        _episode("r1", "r1-ep2"),
        _episode("r1", "r1-ep10"),
        _episode("other", "foreign"),
    ]
    memory.runs = [
        _run("r1", state.run_goal.goal),
        _run("older-same", state.run_goal.goal),
        _run("older-other", "完全不同目标"),
    ]

    context = read_plan_context(state, _runtime(tmp_path, memory))["plan_ctx"]

    assert [item.run_id for item in context.run_index] == ["older-same", "older-other"]
    assert [item.episode_id for item in context.details] == ["r1-ep2", "r1-ep10"]
    assert [req.conditions for req in memory.requests] == [{"run_id": "r1"}, {"runs": "all"}]
    assert all(req.limit == 10**6 for req in memory.requests)


def test_read_plan_context_records_read_run_memory_account(tmp_path: Path) -> None:
    state, memory = _state(), _RecordingMemory()
    memory.runs = [_run("r1", "g"), _run("past", "other")]
    runtime = _runtime(tmp_path, memory)

    read_plan_context(state, runtime)
    events = [parse(event) for event in runtime.context.trace.read_events()]

    assert [event.kind for event in events] == [
        "read_episode_memory",
        "read_run_memory",
    ]
    assert events[-1].content.query == "runs=all" and events[-1].content.refs == ["past"]
    assert events[-1].meta.source == "run.perceive"
    assert events[-1].meta.episode_id == events[-1].meta.task_id == "r1"
    assert events[-1].meta.step == 1


def test_run_knowledge_is_retrieved_every_round_into_plan_ctx(tmp_path: Path) -> None:
    state, memory = _state(), _RecordingMemory()
    runtime = _runtime(tmp_path, memory)
    state = state.model_copy(update=read_plan_context(state, runtime))
    original = state.plan_ctx

    for step in range(2):
        state = state.model_copy(update={"step": step})
        state = state.model_copy(update=retrieve_run_knowledge(state, runtime))

    assert memory.knowledge_queries == 2 and state.plan_ctx.knowledge == ["知识2"]
    assert state.plan_ctx.details is original.details
    assert state.plan_ctx.run_index is original.run_index
    requests = [req for req in memory.requests if req.query]
    assert all(
        req.conditions == {} and req.limit == DEFAULT_APP_CONFIG.memory.recall_limit
        for req in requests
    )
    assert all(f"目标：{state.run_goal.goal}" in req.query for req in requests)
    events = [
        parse(event)
        for event in runtime.context.trace.read_events()
        if event.kind == "read_knowledge"
    ]
    assert [event.meta.step for event in events] == [1, 2]
    assert all(event.meta.source == "run.retrieve_knowledge" for event in events)
    assert all(event.content.refs == ["guide.md"] for event in events)
    assert [event.content.query for event in events] == [req.query for req in requests]


def test_run_perceive_passes_the_new_context_to_the_knowledge_unit(tmp_path: Path) -> None:
    state, memory = _state(), _RecordingMemory()
    memory.episodes = [_episode("r1", "r1-ep1")]
    memory.runs = [_run("past", "different goal")]
    runtime = _runtime(tmp_path, memory)
    observation = state.observation
    runtime.context.game = SimpleNamespace(
        perceive_task=lambda: FromHarnessToGameToolPerceiveTaskResp(
            observation=observation, frame_png="F"
        )
    )
    state = state.model_copy(update={"observation": None, "plan_ctx": None})

    updates = perceive(state, runtime)

    assert updates["observation"] is not None
    assert updates["plan_ctx"].knowledge == ["知识1"]
    assert [entry.episode_id for entry in updates["plan_ctx"].details] == ["r1-ep1"]
    assert [entry.run_id for entry in updates["plan_ctx"].run_index] == ["past"]
    assert len(memory.requests) == 3 and memory.requests[-1].query


def test_run_knowledge_requires_the_sensed_observation(tmp_path: Path) -> None:
    state = _state().model_copy(update={"observation": None, "plan_ctx": PlanContext(details=[])})
    memory = _RecordingMemory()

    with pytest.raises(AssertionError, match="before sense"):
        retrieve_run_knowledge(state, _runtime(tmp_path, memory))

    assert memory.requests == []


def test_episode_query_import_still_exposes_the_shared_function() -> None:
    state = _state()

    query = episode_query(state.observation, state.run_goal.goal)

    assert episode_query is build_knowledge_query
    assert query == build_knowledge_query(state.observation, state.run_goal.goal)
