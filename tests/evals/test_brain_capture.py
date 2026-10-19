"""全脑录制的使用示范：输入不变，异常透传，等待起止独立保存。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from evals.common.brain_capture import record_brain_calls
from evals.common.capture_audit import audit_capture
from evals.common.invocation import RecordingInvocation
from pokemon_agent.schemas.harness import ModelCall, TraceEvent


class Envelope(BaseModel):
    """测试的类型化调用边界；嵌套字段模拟完整历史。"""

    history: list[str]


class CallResponse(BaseModel):
    """同一工具调用允许多个相同的模型尝试。"""

    calls: list[ModelCall]


def test_capture_audit_counts_retries_and_retains_an_unfinished_request(tmp_path: Path) -> None:
    directory = tmp_path / "brain_calls/task/choose"
    payload = {"prompt": "full input", "images": [], "raw": "output"}
    response = CallResponse(calls=[ModelCall(payload=payload), ModelCall(payload=payload)])
    RecordingInvocation(lambda request: response, directory)(Envelope(history=["full history"]))
    (directory / "000002.request.json").write_text('{"history":[]}', encoding="utf-8")
    trace = tmp_path / "trace"
    trace.mkdir()
    for number in (1, 2):
        event = TraceEvent(
            uuid=str(number),
            seq=number,
            kind="choose_call",
            type="model_call",
            started_at=1,
            ended_at=2,
            meta="{}",
            content=json.dumps(payload),
        )
        (trace / f"{number}.json").write_text(event.model_dump_json(), encoding="utf-8")

    report = audit_capture(tmp_path)

    assert report.recorded_attempts == report.trace_attempts == 2
    assert report.missing_from_recording == report.missing_from_trace == 0
    assert report.ports["task/choose"].requests == 2
    assert report.ports["task/choose"].pending == 1


def test_invocation_saves_full_request_before_waiting_and_returns_same_response(
    tmp_path: Path,
) -> None:
    request = Envelope(history=["first", "second"])
    expected = Envelope(history=["result"])

    def invoke(actual: Envelope) -> Envelope:
        assert actual is request
        assert (
            Envelope.model_validate_json((tmp_path / "000001.request.json").read_text("utf-8"))
            == request
        )
        assert (tmp_path / "000001.start.json").exists()
        assert not (tmp_path / "000001.end.json").exists()
        return expected

    actual = RecordingInvocation(invoke, tmp_path)(request)

    assert actual is expected
    end = json.loads((tmp_path / "000001.end.json").read_text("utf-8"))
    assert end["status"] == "success"
    assert end["elapsed_s"] >= 0
    assert request.history == ["first", "second"]


@pytest.mark.parametrize(
    "error", [RuntimeError("transport failed"), KeyboardInterrupt("cancelled")]
)
def test_invocation_records_failure_and_preserves_exception_identity(
    tmp_path: Path, error: BaseException
) -> None:
    def invoke(request: Envelope) -> Envelope:
        raise error

    with pytest.raises(type(error)) as raised:
        RecordingInvocation(invoke, tmp_path)(Envelope(history=[]))

    assert raised.value is error
    assert not (tmp_path / "000001.response.json").exists()
    failure = json.loads((tmp_path / "000001.failure.json").read_text("utf-8"))
    assert failure["error_type"] == type(error).__name__
    end = json.loads((tmp_path / "000001.end.json").read_text("utf-8"))
    assert end["status"] == "failure"


def test_all_runtime_ports_are_recorded_in_separate_layer_directories(tmp_path: Path) -> None:
    expected = Envelope(history=["unchanged response"])
    seen: list[Envelope] = []

    def invoke(request: Envelope) -> Envelope:
        seen.append(request)
        return expected

    original = SimpleNamespace(
        plan=invoke,
        decompose=invoke,
        choose=invoke,
        judge=invoke,
        verify=invoke,
        reflect=invoke,
        summarize=invoke,
        summarize_task=invoke,
        summarize_run=invoke,
    )
    task = SimpleNamespace(
        chooser=original,
        judger=original,
        verifier=original,
        reflector=original,
        task_summarizer=original,
    )
    episode = SimpleNamespace(
        task=task,
        decomposer=original,
        judger=original,
        verifier=original,
        summarizer=original,
    )
    runtime = SimpleNamespace(
        episode=episode,
        planner=original,
        judger=original,
        run_summarizer=original,
    )
    request = Envelope(history=["all details", "background index"])

    record_brain_calls(runtime, tmp_path)
    for owner, field, method in (
        (runtime, "planner", "plan"),
        (runtime, "judger", "judge"),
        (runtime, "run_summarizer", "summarize_run"),
        (episode, "decomposer", "decompose"),
        (episode, "judger", "judge"),
        (episode, "verifier", "verify"),
        (episode, "summarizer", "summarize"),
        (task, "chooser", "choose"),
        (task, "judger", "judge"),
        (task, "verifier", "verify"),
        (task, "reflector", "reflect"),
        (task, "task_summarizer", "summarize_task"),
    ):
        assert getattr(getattr(owner, field), method)(request) is expected

    assert len(seen) == 12
    assert all(item is request for item in seen)
    assert len(list(tmp_path.rglob("*.request.json"))) == 12
    for layer in ("run", "episode", "task"):
        assert (tmp_path / layer / "judge/000001.response.json").exists()
