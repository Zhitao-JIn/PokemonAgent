"""Version stamps survive failed attempts, success, and local/Langfuse trace round trips."""

import json
from pathlib import Path

import pytest
from _fake_langfuse import FakeLangfuseClient

from pokemon_agent.direct.brain_tool import render_and_stamp
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, ModelCall, TraceKind
from pokemon_agent.trace import LangfuseTrace

from .unit_fixtures import ExampleParams, make_registry, make_unit


@pytest.mark.parametrize("backend", ["local", "langfuse"])
def test_every_attempt_keeps_its_prompt_stamp_through_trace(tmp_path: Path, backend: str) -> None:
    make_unit(tmp_path / "units")
    gateway = PromptGateway(make_registry(tmp_path / "units", example="v1"))
    calls = [
        ModelCall(
            payload={"ok": "false", "raw": "{broken", "prompt": "Hello Red.\n"},
            error_kind="ParseFailure",
            error="invalid JSON",
        ),
        ModelCall(payload={"ok": "true", "raw": "{}", "prompt": "Hello Red.\n"}),
    ]
    if backend == "local":
        trace = TraceTool.build(run_id="run-1", trace_root=tmp_path / "trace")
    else:
        client = FakeLangfuseClient()
        trace = TraceTool(
            LangfuseTrace(trace_id=client.create_trace_id(seed="run-1"), client=client),
            run_id="run-1",
        )

    rendered = render_and_stamp(gateway, "example", ExampleParams(value="Red"), calls)
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            calls=calls,
            meta={"source": "choose", "episode_id": "ep-1", "task_id": "task-1", "step": 1},
        )
    )
    events = trace.read_events()

    assert rendered.text == "Hello Red.\n"
    assert [event.kind for event in events] == [
        TraceKind.CHOOSE_CALL,
        TraceKind.CALL_FAILED,
        TraceKind.CHOOSE_CALL,
    ]
    stamp = {"prompt_task": "example", "prompt_version": "v1", "prompt_hash": rendered.hash}
    model_events = [event for event in events if event.kind == TraceKind.CHOOSE_CALL]
    for call, event in zip(calls, model_events, strict=True):
        assert {key: call.payload[key] for key in stamp} == stamp
        assert json.loads(event.content) == call.payload
        decoded = parse(event).content.model_dump()
        assert {key: decoded[key] for key in stamp} == stamp
        assert decoded["prompt"] == call.payload["prompt"]
        assert decoded["raw"] == call.payload["raw"]
    assert calls[0].error_kind == "ParseFailure" and calls[0].error == "invalid JSON"
    assert not calls[1].error_kind
