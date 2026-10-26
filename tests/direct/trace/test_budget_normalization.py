"""Scalar budgets become typed proposals in one call, with the original and conversion on disk."""

import json
from pathlib import Path

import pytest
from _doubles.http import FakeUrlopen, ok_body
from _harness_fixtures.app_config import app_config

from pokemon_agent.brain.interface import Goal
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)


def test_scalar_budget_and_provider_identity_survive_real_assembly_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
    raw = json.dumps(
        {"new_items": [{"goal": "g", "success_criteria": "c", "budget": 2}], "why": "evidence"}
    )
    fake = FakeUrlopen(body=ok_body(text=raw))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    app = app_config(retry={"brain_max_attempts": 1})
    tools = BrainTool.build(
        links=("plan",),
        layer="run",
        models=app.models,
        retry=app.retry,
        request_timeouts=app.request_timeouts_s,
        action_limits=app.action_limits,
        image_cap=app.memory.scope_image_cap,
    )
    trace = TraceTool.build(run_id="r1", trace_root=tmp_path)

    response = tools.planner.plan(
        FromHarnessToBrainToolPlanOnceReq(
            run_goal=Goal(goal="parent", criteria="done"), run_id="r1", plan=[], max_push=1
        )
    )
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.PLAN_CALL,
            calls=response.calls,
            meta={"source": "plan_run", "episode_id": "r1", "task_id": "r1", "step": 1},
        )
    )
    content = parse(trace.read_events()[0]).content

    assert fake.call_count == len(response.calls) == 1
    assert response.plan.new_items[0].budget.model_dump() == {"limit": 2, "unit": "tasks"}
    assert content.raw == raw
    assert content.normalizations == ["new_items[0].budget: limit=2, unit=tasks"]
    assert (content.provider, content.model) == ("deepseek", app.models.plan.model)
