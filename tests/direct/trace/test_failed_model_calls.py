"""模型拒绝和重试的调用账、错误账必须都能落盘并读回。"""

from pathlib import Path

import pytest

from pokemon_agent.brain.interface import VerifyVerdict
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, ModelCall, TraceKind


@pytest.mark.parametrize("kind", [TraceKind.VERIFY_CALL, TraceKind.JUDGE_CALL])
def test_rejected_call_without_a_result_preserves_the_model_and_error_events(
    tmp_path: Path, kind: TraceKind
) -> None:
    trace = TraceTool.build(run_id="probe", trace_root=tmp_path)
    call = ModelCall(
        payload={"ok": "false", "prompt": "verify this", "raw": ""},
        error_kind="ProviderRejected",
        error="HTTP 402: Insufficient Balance",
    )

    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=kind,
            calls=[call],
            meta={"source": "verify", "episode_id": "ep", "task_id": "task", "step": 1},
        )
    )

    events = [parse(event) for event in trace.read_events()]
    assert [event.kind for event in events] == [kind, TraceKind.CALL_FAILED]
    assert events[0].content.prompt == call.payload["prompt"]
    assert not events[0].content.ok
    assert events[1].content.exception == "ProviderRejected"
    assert events[1].content.reason == call.error


def test_verify_retry_keeps_error_schema_separate_from_the_returned_verdicts(
    tmp_path: Path,
) -> None:
    trace = TraceTool.build(run_id="probe", trace_root=tmp_path)
    calls = [
        ModelCall(payload={"ok": "false"}, error_kind="ParseFailure", error="invalid JSON"),
        ModelCall(payload={"ok": "true"}),
    ]
    verdict = VerifyVerdict(index=0, positive=True, why="matches goal")

    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_CALL,
            calls=calls,
            verdicts=[verdict],
            meta={"source": "verify", "episode_id": "ep", "task_id": "task", "step": 1},
        )
    )

    events = [parse(event) for event in trace.read_events()]
    assert [event.kind for event in events] == [
        TraceKind.VERIFY_CALL,
        TraceKind.CALL_FAILED,
        TraceKind.VERIFY_CALL,
    ]
    assert events[1].content.reason == "invalid JSON"
    assert events[2].content.verdicts == [verdict.model_dump()]
