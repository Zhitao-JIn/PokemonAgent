"""Model identity survives BrainTool translation and disk trace round trips."""

import json
from pathlib import Path

import pytest
from _doubles.http import FakeUrlopen, ok_body
from _harness_fixtures.app_config import app_config

from pokemon_agent.brain.interface import Goal
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.direct.trace.content import ModelCallContent
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene


@pytest.mark.parametrize("identity", [{}, {"provider": "qwen", "model": "qwen3.8-flash"}])
def test_model_call_content_reads_both_old_and_recorded_identity(identity: dict[str, str]) -> None:
    content = ModelCallContent.model_validate({"input_tokens": "11", **identity})

    assert content.input_tokens == 11
    assert content.provider == identity.get("provider", "")
    assert content.model == identity.get("model", "")


@pytest.mark.parametrize("rejected", [False, True])
def test_brain_identity_survives_real_budget_wrapping_and_disk_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rejected: bool
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "placeholder")
    fake = FakeUrlopen(body=ok_body(text='{"action": "up"}'))
    if rejected:
        fake.http_error(402)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    app = app_config(retry={"brain_max_attempts": 1})
    chooser = BrainTool.build(
        links=("text",),
        layer="task",
        models=app.models,
        retry=app.retry,
        request_timeouts=app.request_timeouts_s,
        action_limits=app.action_limits,
        image_cap=app.memory.scope_image_cap,
    ).chooser
    trace = TraceTool.build(run_id="r1", trace_root=tmp_path)

    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="g", criteria="c")],
        obs=TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK),
        space=ActionSpace(names=["up"], descriptions={"up": "north"}),
        memories=[],
    )
    if rejected:
        with pytest.raises(MaxRetriesExceeded) as caught:
            chooser.choose(request)
        calls = caught.value.calls
    else:
        calls = chooser.choose(request).calls
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            calls=calls,
            meta={"source": "plan_task", "episode_id": "e1", "task_id": "t1", "step": 1},
        )
    )
    raw = trace.read_events()[0]
    persisted = json.loads(raw.content)
    content = parse(raw).content

    assert calls[0].payload["provider"] == persisted["provider"] == "qwen"
    assert calls[0].payload["model"] == persisted["model"] == "qwen3.8-flash"
    assert fake.call_count == len(calls) == 1
    assert isinstance(content, ModelCallContent)
    assert (content.provider, content.model) == ("qwen", "qwen3.8-flash")
