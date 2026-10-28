"""旧脑调用 trace 对账测试；随旧采集管线退役。"""

import json
from pathlib import Path

from pydantic import BaseModel

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
