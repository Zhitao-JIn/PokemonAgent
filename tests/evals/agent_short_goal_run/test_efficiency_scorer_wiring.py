"""Independent Inspect scorers read real disk traces without starting a worker or model."""

import asyncio
import json

import pytest
from _efficiency_fixtures import action, example_sample, example_stream, frame
from inspect_ai._util.registry import registry_info
from inspect_ai.scorer import NOANSWER, Target
from inspect_ai.solver import TaskState
from inspect_ai.util import Store, store_as
from inspect_ai.util._store import init_subtask_store

from evals.agent_short_goal_run.scorer.decision_scorer import decision_actions_scorer
from evals.agent_short_goal_run.scorer.duration_scorer import run_duration_scorer
from evals.agent_short_goal_run.solver.record import AgentRunRecord
from evals.agent_short_goal_run.task import agent_short_goal_run
from pokemon_agent.schemas.harness import TraceEvent


@pytest.fixture
def recorded_run(tmp_path, monkeypatch):
    init_subtask_store(Store())
    record = store_as(AgentRunRecord)
    record.run_id, record.branch, record.work_dir = "run", "main", str(tmp_path)
    root = tmp_path / "trace"
    root.mkdir()
    stream = example_stream(frame(), action(), frame(map_id=2))
    for index, item in enumerate(stream.events):
        raw = TraceEvent(
            uuid=item.uuid,
            seq=index,
            kind=item.kind,
            type=item.type,
            started_at=item.started_at,
            ended_at=item.ended_at,
            meta=item.meta.model_dump_json(),
            content=item.content.model_dump_json(),
        )
        (root / f"{raw.uuid}.json").write_text(raw.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        "evals.agent_short_goal_run.scorer.trace_adapter.load", lambda _: [example_sample()]
    )
    state = TaskState(
        model="none",
        sample_id="goal",
        epoch=2,
        input="",
        messages=[],
        metadata={"sample_id": "goal", "dataset_version": "test"},
    )
    yield state, record, root


def test_independent_scorer_reads_trace_and_labels_success_without_running_success_scorer(
    recorded_run,
):
    state, _, _ = recorded_run

    result = asyncio.run(decision_actions_scorer("local", (3, 3))(state, Target("")))

    assert result.value == 1
    assert result.metadata["successful"] is True
    assert result.metadata["epoch"] == 2
    assert result.metadata["unit"] == "actions"


def test_incomplete_run_does_not_report_a_deceptively_short_duration(recorded_run):
    state, _, root = recorded_run
    for path in root.glob("*.json"):
        if json.loads(path.read_text())["kind"] == "run_end":
            path.unlink()

    result = asyncio.run(run_duration_scorer("local", (3, 3))(state, Target("")))

    assert result.value == NOANSWER


def test_invalid_worker_record_does_not_read_or_count_an_execution(recorded_run):
    state, record, _ = recorded_run
    record.invalid = "invalid initial state"

    result = asyncio.run(decision_actions_scorer("local", (3, 3))(state, Target("")))

    assert result.value == NOANSWER
    assert result.metadata["invalid"] is True


def test_task_exposes_eight_independent_core_scorers_and_preserves_optional_qwen(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("evals.agent_short_goal_run.task.load_env_file", lambda: None)

    task = agent_short_goal_run(
        samples=["knowledge_door_transition"], log_dir=str(tmp_path), grader_model="none"
    )

    assert [registry_info(item).name for item in task.scorer] == [
        "e2e_scorer",
        "movement_steps_scorer",
        "decision_actions_scorer",
        "ineffective_repetition_scorer",
        "post_completion_actions_scorer",
        "model_calls_scorer",
        "run_duration_scorer",
        "success_cost_scorer",
    ]
