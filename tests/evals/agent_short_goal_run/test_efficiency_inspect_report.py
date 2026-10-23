"""A full Inspect report exposes each metric independently without any real model calls."""

import asyncio
import math
from pathlib import Path

from _efficiency_fixtures import action, example_sample, example_stream, frame, write_trace
from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_ai.util import store_as

from evals.agent_short_goal_run.scorer.cost_scorer import success_cost_scorer
from evals.agent_short_goal_run.scorer.decision_scorer import decision_actions_scorer
from evals.agent_short_goal_run.scorer.duration_scorer import run_duration_scorer
from evals.agent_short_goal_run.scorer.model_calls_scorer import model_calls_scorer
from evals.agent_short_goal_run.scorer.movement_scorer import movement_steps_scorer
from evals.agent_short_goal_run.scorer.overshoot_scorer import post_completion_actions_scorer
from evals.agent_short_goal_run.scorer.repeat_scorer import ineffective_repetition_scorer
from evals.agent_short_goal_run.scorer.task_scorer import e2e_scorer
from evals.agent_short_goal_run.solver.record import AgentRunRecord


@solver
def saved_trace(work_dir: str):
    """Expose an existing trace to Inspect; generate is deliberately never called."""

    async def solve(state, generate):
        record = store_as(AgentRunRecord)
        record.run_id, record.branch, record.work_dir = "run", "main", work_dir
        return state

    return solve


def replay_task(work: Path) -> Task:
    """The success column and seven independent efficiency columns share one saved trace."""
    factories = [
        movement_steps_scorer,
        decision_actions_scorer,
        ineffective_repetition_scorer,
        post_completion_actions_scorer,
        model_calls_scorer,
        run_duration_scorer,
        success_cost_scorer,
    ]
    return Task(
        dataset=[
            Sample(
                input="Replay",
                id="goal",
                metadata={
                    "sample_id": "goal",
                    "dataset_version": "test",
                },
            )
        ],
        solver=saved_trace(str(work)),
        scorer=[
            e2e_scorer(stall_limits=(3, 3)),
            *[factory("local", (3, 3)) for factory in factories],
        ],
    )


def test_inspect_report_keeps_independent_scorers_and_unreduced_epoch_counts(tmp_path, monkeypatch):
    work = tmp_path / "saved"
    write_trace(work / "trace", example_stream(frame(), action(), frame(map_id=2)))
    monkeypatch.setattr(
        "evals.agent_short_goal_run.scorer.trace_adapter.load", lambda _: [example_sample()]
    )
    monkeypatch.setattr(
        "evals.agent_short_goal_run.scorer.task_scorer.load_samples", lambda _: [example_sample()]
    )

    logs = asyncio.run(
        eval_async(
            replay_task(work), model="mockllm/model", epochs=2, log_dir=str(tmp_path / "report")
        )
    )

    assert logs[0].status == "success"
    summaries = {s.name: s for s in logs[0].results.scores}
    assert len(summaries) == 8
    decisions = summaries["decision_actions_scorer"].metrics
    assert decisions["measured_count"].value == 2
    assert decisions["successful_median"].value == 1
    assert math.isnan(decisions["failed_median"].value)
    cost = summaries["success_cost_scorer"].metrics
    assert cost["measured_count"].value == 0
    assert math.isnan(cost["cost_per_success"].value)
