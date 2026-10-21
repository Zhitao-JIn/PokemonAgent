"""run 收尾链的用法：终态蒸馏、耗尽空章与幂等落库。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import DEFAULT_APP_CONFIG, call_policy, reconfigure
from _harness_fixtures.brain import _Brain
from _harness_fixtures.harness import GOAL, build_fake
from _harness_fixtures.memory import _Memory
from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal
from pokemon_agent.direct.brain_tool import RunSummarizer
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.harness.run.run_graph import compile_run_graph
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.harness.run.store_run_memory import store_run_memory
from pokemon_agent.harness.run.summarize_run import summarize_run
from pokemon_agent.schemas.harness import ModelCall
from pokemon_agent.schemas.harness.domain import EpisodeOutput, Termination
from pokemon_agent.schemas.memory import EpisodeMemory


def _state(with_memory: bool = True) -> RunState:
    memory = (
        EpisodeMemory(
            run_id="r1",
            run_goal="总目标",
            episode_id="r1-ep1",
            goal="局目标",
            steps=1,
            summary="素材。",
            markdown="素材。",
            quality_score=0.5,
            quality_rationale="q",
        )
        if with_memory
        else None
    )
    outputs = [
        EpisodeOutput(
            episode_id="r1-ep1",
            goal_id="g1",
            termination=Termination.GOAL_DONE,
            tasks_used=1,
            acts_used=4,
            memory=memory,
        ),
        EpisodeOutput(
            episode_id="r1-ep2",
            goal_id="g2",
            termination=Termination.STALLED,
            tasks_used=2,
            acts_used=7,
        ),
    ]
    return RunState(
        run_id="r1",
        run_goal=Goal(goal="总目标", criteria="c"),
        goals=[],
        step=2,
        episode_outputs=outputs,
        termination=Termination.STALLED,
    )


def _runtime(tmp_path: Path, summarizer: object) -> Runtime:
    return Runtime(
        context=SimpleNamespace(
            run_summarizer=summarizer,
            config=DEFAULT_APP_CONFIG,
            memory=_Memory(),
            trace=TraceTool.build(run_id="r1", trace_root=tmp_path),
        )
    )


def _summarizer() -> RunSummarizer:
    return RunSummarizer(
        _Brain(lambda n: True, lambda n: True, lambda n: True, 1), policy=call_policy()
    )


def test_every_edge_into_run_done_goes_through_the_run_summary_cells() -> None:
    graph = compile_run_graph().get_graph()

    incoming = [edge for edge in graph.edges if edge.target == "run_done"]

    assert incoming
    assert {edge.source for edge in incoming} == {"store_run_memory"}
    assert any(
        edge.source == "summarize_run" and edge.target == "store_run_memory" for edge in graph.edges
    )


def test_store_run_memory_writes_once_even_when_called_twice(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, _summarizer())
    state = _state()
    state = state.model_copy(update=summarize_run(state, runtime))

    store_run_memory(state, runtime)
    original = runtime.context.memory.runs[0].model_dump()
    changed = state.model_copy(
        update={"run_memory": state.run_memory.model_copy(update={"summary": "替换"})}
    )
    store_run_memory(changed, runtime)

    assert len(runtime.context.memory.runs) == 1
    assert runtime.context.memory.runs[0].model_dump() == original
    assert [event.kind for event in runtime.context.trace.read_events({})].count(
        "write_run_memory"
    ) == 1


@pytest.mark.parametrize("failure", ["retries", "budget", "empty"])
def test_run_summary_failure_degrades_to_an_empty_chapter(tmp_path: Path, failure: str) -> None:
    calls = [ModelCall(payload={"ok": "false"}, error_kind="ParseFailure", error="bad")]
    error = (
        MaxRetriesExceeded(1, "bad", calls, source="summarize_run")
        if failure == "retries"
        else BudgetExhausted("summarize_run", calls)
    )

    class FailingSummarizer:
        def summarize_run(self, req):
            raise error

    runtime = _runtime(tmp_path, FailingSummarizer())
    state = _state(with_memory=failure != "empty")

    memory = summarize_run(state, runtime)["run_memory"]
    events = runtime.context.trace.read_events({})

    assert memory.summary == ""
    assert memory.quality_score == 0.0
    assert (
        "无可蒸素材" if failure == "empty" else type(error).__name__
    ) in memory.quality_rationale
    assert memory.episodes == 2 and memory.succeeded == 1 and memory.acts_used == 11
    assert any(event.kind == "call_exhausted" for event in events)
    assert any(event.kind == "summarize_run_call" for event in events) == (failure != "empty")


def test_run_summary_writes_run_memory_with_source_chapter_stamped_by_harness(
    tmp_path: Path,
) -> None:
    state = _state()
    runtime = _runtime(tmp_path, _summarizer())

    memory = summarize_run(state, runtime)["run_memory"]

    assert memory.run_id == state.run_id
    assert memory.run_goal == state.run_goal.goal
    assert (memory.episodes, memory.succeeded, memory.acts_used) == (2, 1, 11)
    assert memory.termination == "stalled"
    assert not memory.success
    assert memory.summary == "run summary"


@pytest.mark.parametrize("actions_exhausted", [False, True])
def test_run_summary_cells_run_after_done_in_a_full_graph_run(
    tmp_path: Path, actions_exhausted: bool
) -> None:
    fake = build_fake(tmp_path)
    if actions_exhausted:
        reconfigure(fake.run_rt, budget={"max_total_actions": 0})

    fake.harness.run("r1", [GOAL])
    events = fake.trace.read_events({})

    assert len(fake.memory.runs) == 1
    assert sum(event.kind == "write_run_memory" for event in events) == 1
    assert events[-1].kind == "run_end"
    assert any(event.kind == "read_run_memory" for event in events) == (not actions_exhausted)
    if actions_exhausted:
        assert fake.memory.runs[0].termination == "actions_exhausted"
    else:
        assert fake.memory.runs[0].summary == "run summary"
