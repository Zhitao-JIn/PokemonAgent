"""同总目标的其他局索引跨 run 召回，空目标也留下查询账。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from _harness_fixtures.memory import _Memory
from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.perceive.retrieve_episode_index import retrieve_episode_index
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
)
from pokemon_agent.schemas.memory import EpisodeMemory


class _RecordingMemory(_Memory):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[FromHarnessToMemoryToolRecallReq] = []

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        self.requests.append(req)
        response = super().recall(req)
        unrelated = FromHarnessToMemoryToolRecallItem(kind="knowledge", uuid="k", payload={})
        return response.model_copy(update={"items": [*response.items, unrelated]})


def _memory(run: str, episode: str, goal: str) -> EpisodeMemory:
    return EpisodeMemory(
        run_id=run,
        run_goal=goal,
        episode_id=episode,
        goal="局目标",
        steps=1,
        summary="首句。正文第二句不该进入索引。",
        markdown="完整正文",
        quality_score=0.5,
        quality_rationale="q",
    )


def _state(goal: str) -> EpisodeRunState:
    return EpisodeRunState(
        run_id="r1",
        run_goal=goal,
        episode_id="current",
        step=2,
        goal=Task(task_id="g", goal="局目标", success_criteria="c", max_steps=5),
        ep_ctx=EpisodeContext(episode_index=[_memory("r1", "stale", "old")]),
    )


def _retrieve(
    state: EpisodeRunState, memory: _RecordingMemory, root: Path
) -> tuple[EpisodeContext, TraceTool]:
    trace = TraceTool.build(run_id=state.run_id, trace_root=root)
    runtime = Runtime(context=SimpleNamespace(memory=memory, trace=trace))
    updates = retrieve_episode_index(state, runtime)
    return updates["ep_ctx"], trace


@pytest.mark.parametrize("goal", ["same goal", "通关 第一 道馆", " goal with spaces "])
def test_episode_index_excludes_current_episode_and_other_run_goals(
    tmp_path: Path, goal: str
) -> None:
    memory = _RecordingMemory()
    memory.episodes = [
        _memory("r1", "current", goal),
        _memory("r1", "earlier", goal),
        _memory("r2", "another-run", goal),
        _memory("r1", "different", goal + "!"),
    ]

    context, _trace = _retrieve(_state(goal), memory, tmp_path)

    assert [entry.episode_id for entry in context.episode_index] == ["earlier", "another-run"]
    assert memory.requests[0].conditions == {"run_goal": goal}
    assert memory.requests[0].limit == 10**6
    assert [entry.run_id for entry in context.episode_index] == ["r1", "r2"]


def test_an_empty_run_goal_clears_the_index_without_calling_recall(tmp_path: Path) -> None:
    state, memory = _state(""), _RecordingMemory()

    context, trace = _retrieve(state, memory, tmp_path)

    assert memory.requests == [] and context.episode_index == []
    events = [parse(event) for event in trace.read_events()]
    assert len(events) == 1
    assert events[0].content.query == "run_goal=" and events[0].content.refs == []


def test_episode_index_account_records_run_goal_query_and_refs(tmp_path: Path) -> None:
    goal, memory = "通关 第一 道馆", _RecordingMemory()
    memory.episodes = [_memory("r1", "current", goal), _memory("r2", "foreign", goal)]

    _context, trace = _retrieve(_state(goal), memory, tmp_path)
    events = [parse(event) for event in trace.read_events()]

    assert len(events) == 1
    assert events[0].kind == "read_episode_memory"
    assert events[0].meta.source == "retrieve_episode_index"
    assert events[0].meta.step == 3 and events[0].meta.episode_id == "current"
    assert events[0].content.query == f"run_goal={goal}"
    assert events[0].content.refs == ["foreign"]
