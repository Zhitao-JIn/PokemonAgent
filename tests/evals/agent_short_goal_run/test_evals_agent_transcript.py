"""S1b 的使用示范：类型化账本回放与 store 交接，不调用游戏或模型。"""

import asyncio
import json
import subprocess
from collections import Counter

import pytest
from inspect_ai.event import InfoEvent, ModelEvent, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import ContentImage
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState
from inspect_ai.util import Store, store_as
from inspect_ai.util._store import init_subtask_store

from evals.agent_short_goal_run.scorer.result_grade import final_evidence
from evals.agent_short_goal_run.scorer.stream import RunStream
from evals.agent_short_goal_run.scorer.task_scorer import e2e_scorer
from evals.agent_short_goal_run.solver.record import AgentRunRecord
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.agent_short_goal_run.solver.transcript import replay_into_transcript
from pokemon_agent.direct.trace.content import EventMeta, ModelCallContent, OtherContent
from pokemon_agent.direct.trace.parse import ParsedEvent


@pytest.fixture
def transcript():
    current = Transcript()
    init_transcript(current)
    init_subtask_store(Store())
    yield current
    init_transcript(Transcript())
    init_subtask_store(Store())


def trace_event(index, kind, content=None):
    return ParsedEvent(
        uuid=f"trace-{index}",
        kind=kind,
        type="model_call" if kind == "choose_call" else "test",
        started_at=1000 + index,
        ended_at=1000.25 + index,
        meta=EventMeta(run_id="run", branch="restored", episode_id="episode", task_id="task"),
        content=content or OtherContent(value=kind),
    )


def test_replay_preserves_nested_spans_images_fields_and_original_times(transcript):
    image = "data:image/png;base64,aGVsbG8="
    call = ModelCallContent(
        prompt="choose",
        raw="right",
        images=[image],
        input_tokens=12,
        output_tokens=3,
        cached_tokens=4,
        reasoning_tokens=2,
        ok=False,
        error="provider failed",
        extra_field="preserved",
    )
    kinds = [
        "run_start",
        "episode_start",
        "task_start",
        "choose_call",
        "act_call",
        "read_task",
        "judge_verdict",
        "task_end",
        "task_error",
        "episode_end",
        "run_end",
    ]
    source = [
        trace_event(i, kind, call if kind == "choose_call" else None)
        for i, kind in enumerate(kinds)
    ]

    count = replay_into_transcript(RunStream(source), {"text_model": "actual-model"})

    events = list(transcript.events)
    assert count == len(events) == len(source) + 6
    assert len({event.uuid for event in events}) == count
    primary = [event for event in events if event.uuid in {s.uuid for s in source}]
    assert [e.uuid for e in primary] == [s.uuid for s in source]
    assert [e.timestamp.timestamp() for e in primary] == [s.started_at for s in source]
    begins = [e for e in events if isinstance(e, SpanBeginEvent)]
    ends = [e for e in events if isinstance(e, SpanEndEvent)]
    assert [e.type for e in begins] == ["run", "episode", "task"]
    assert [e.parent_id for e in begins] == [None, begins[0].id, begins[1].id]
    assert [e.id for e in ends] == [e.id for e in reversed(begins)]
    model = next(e for e in events if isinstance(e, ModelEvent))
    assert model.model == model.output.model == "actual-model"
    assert model.role == "choose_call" and model.error == "provider failed"
    assert isinstance(model.input[0].content[1], ContentImage)
    assert model.input[0].content[1].image == image
    assert model.call.request["content"]["images"] == [image]
    assert model.call.request["content"]["extra_field"] == "preserved"
    assert model.call.request["meta"]["branch"] == "restored"
    assert model.output.usage.input_tokens_cache_read == 4
    assert model.output.usage.reasoning_tokens == 2
    assert model.completed.timestamp() == source[3].ended_at and model.working_time == 0.25
    assert [e.function for e in events if isinstance(e, ToolEvent)] == ["act_call", "read_task"]
    assert all(e.metadata["trace_uuid"] in {s.uuid for s in source} for e in events)


def test_unmatched_error_does_not_close_parent_and_unfinished_spans_close_at_trace_end(transcript):
    source = [
        trace_event(0, "run_start"),
        trace_event(1, "task_error"),
        trace_event(2, "episode_start"),
        trace_event(3, "judge_verdict"),
    ]

    replay_into_transcript(RunStream(source), {})

    ends = [e for e in transcript.events if isinstance(e, SpanEndEvent)]
    assert [e.id for e in ends] == ["trace-2", "trace-0"]
    assert all(e.timestamp.timestamp() == source[-1].ended_at for e in ends)


def test_all_model_calls_keep_complete_requests_beyond_inspect_default_limit(transcript):
    source = [
        trace_event(i, "choose_call", ModelCallContent(prompt="hello", raw="ok")) for i in range(30)
    ]

    replay_into_transcript(RunStream(source), {})

    assert all(e.call is not None and e.model == "choose_call" for e in transcript.events)
    assert transcript._log_model_api is None
    with pytest.raises(ValueError, match="Duplicate event uuid"):
        replay_into_transcript(RunStream(source), {})


@pytest.mark.parametrize("mode", ["enabled", "disabled", "invalid", "timeout"])
def test_solver_writes_store_and_scorer_uses_its_run_location(
    tmp_path, monkeypatch, transcript, mode
):
    sample_id = "knowledge_door_transition"
    work = tmp_path / "runs" / sample_id
    work.mkdir(parents=True)
    (work / "run.json").write_text(
        json.dumps(
            {
                "run_id": "custom-run",
                "branch": "custom-branch",
                "invalid": "bad archive" if mode == "invalid" else "",
                "error": "",
            }
        ),
        encoding="utf-8",
    )
    (work / "run_result.json").write_text('{"termination":"success"}', encoding="utf-8")
    loads = []

    def subprocess_run(*args, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired("run-one", 1)

    def load(root, run_id, branch=None, backend="local"):
        loads.append((root, run_id, branch, backend))
        return RunStream([])

    monkeypatch.setattr(subprocess, "run", subprocess_run)
    monkeypatch.setattr(RunStream, "load", load)
    state = TaskState(
        model="none",
        sample_id=sample_id,
        epoch=1,
        input="run",
        messages=[],
        metadata={"sample_id": sample_id, "dataset_version": "v1"},
    )
    solve = run_one_solver(
        report_dir=str(tmp_path),
        run_config_path=str(tmp_path / "run_config.json"),
        models={},
        knowledge=False,
        speed=0,
        timeout=1,
        transcript=mode != "disabled",
        trace_backend="langfuse",
    )

    asyncio.run(solve(state, None))
    record = store_as(AgentRunRecord)
    score = asyncio.run(
        e2e_scorer(stall_limits=(3, 3), trace_backend="langfuse")(state, Target(""))
    )
    final_evidence(record, "langfuse")

    assert record.work_dir == str(work)
    assert state.output.completion == ("timeout" if mode == "timeout" else record.run_result)
    assert score.metadata["run_id"] == record.run_id
    if mode in {"enabled", "disabled"}:
        assert record.run_id == "custom-run" and record.branch == "custom-branch"
        assert loads == [(work / "trace", "custom-run", "custom-branch", "langfuse")] * (
            3 if mode == "enabled" else 2
        )
    else:
        assert record.invalid and not loads and score.value == "N"
        assert any(
            isinstance(e, InfoEvent) and e.source == "agent_short_goal_run"
            for e in transcript.events
        )


def test_replay_covers_historical_tools_and_preserves_their_json(transcript):
    kinds = [
        "press_key",
        "run_macro",
        "get_action_space",
        "read_episode",
        "write_task",
        "sense_frame",
    ]

    replay_into_transcript(RunStream([trace_event(i, kind) for i, kind in enumerate(kinds)]), {})

    assert Counter(type(e).__name__ for e in transcript.events) == {"ToolEvent": 5, "InfoEvent": 1}
    assert json.loads(transcript.events[0].result) == {"value": "press_key"}
