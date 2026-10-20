"""服务拒绝时，真图仍完成错误结算，录制与生产 trace 保持闭合。"""

import json
from pathlib import Path

import pytest
from _harness_fixtures.harness import GOAL, build_fake

from evals.common.brain_capture import record_brain_calls
from evals.common.capture_audit import audit_capture
from evals.common.capture_review import audit_review
from pokemon_agent.direct.trace import parse
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToBrainToolVerifyResp,
    ModelCall,
    TraceKind,
)


class RejectedVerifier:
    """相同 VerifyPort；模拟一次供应商拒绝并携带完整失败账。"""

    def verify(self, req: FromHarnessToBrainToolVerifyReq) -> FromHarnessToBrainToolVerifyResp:
        """有待校验记忆时抛出带调用账的耗尽异常。"""
        assert req.entries
        reason = "HTTP 402: Insufficient Balance"
        call = ModelCall(
            payload={"ok": "false", "prompt": req.goal, "raw": ""},
            error_kind="ProviderRejected",
            error=reason,
        )
        raise MaxRetriesExceeded(1, reason, [call], source="verify")


@pytest.mark.parametrize("layer", ["task", "episode"])
def test_rejected_verification_finishes_the_run_without_losing_capture_evidence(
    tmp_path: Path,
    layer: str,
) -> None:
    fake = build_fake(tmp_path)
    runtime = fake.run_rt.episode.task if layer == "task" else fake.run_rt.episode
    runtime.verifier = RejectedVerifier()
    record_brain_calls(fake.run_rt, tmp_path / "brain_calls")

    result = fake.harness.run("r1", [GOAL])

    calls, waits = audit_capture(tmp_path), audit_review(tmp_path)
    assert result.termination is not None
    assert calls.ports[f"{layer}/verify"].failures > 0
    assert calls.missing_from_recording == calls.missing_from_trace == 0
    assert not any(port.pending for port in calls.ports.values())
    assert waits.pending == waits.failed == waits.missing == 0
    events = [parse(event) for event in fake.trace.read_events()]
    errors = [event.content for event in events if event.kind == TraceKind.CALL_FAILED]
    assert any(error.exception == "ProviderRejected" and "402" in error.reason for error in errors)
    assert any(event.kind == TraceKind.CALL_EXHAUSTED for event in events)
    failure = next((tmp_path / "brain_calls" / layer / "verify").glob("*.failure.json"))
    assert "402" in json.loads(failure.read_text("utf-8"))["error"]
