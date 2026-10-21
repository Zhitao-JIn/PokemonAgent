"""核对完整录制与生产 trace 的模型尝试，不把零调用误报成遗漏。"""

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

KINDS: dict[str, str] = {
    "choose": "choose_call",
    "judge": "judge_call",
    "plan": "plan_call",
    "decompose": "decompose_call",
    "verify": "verify_call",
    "summarize": "summarize_episode_call",
    "summarize_task": "summarize_task_call",
    "summarize_run": "summarize_run_call",
}


class PortCoverage(BaseModel):
    """每层每口的调用数；等待未结束保留 pending。"""

    requests: int = 0
    successes: int = 0
    failures: int = 0
    pending: int = 0
    elapsed_s: float = 0
    model_attempts: int = 0
    model_elapsed_s: float = 0


class CaptureAudit(BaseModel):
    """trace 和录制双向对账；覆盖数与遗漏数分列。"""

    ports: dict[str, PortCoverage] = Field(default_factory=dict)
    trace_attempts: int = 0
    recorded_attempts: int = 0
    missing_from_recording: int = 0
    missing_from_trace: int = 0


def _signature(kind: str, payload: dict[str, object]) -> str:
    """以实际模型文本、图像、原始返回关联，重复调用保留次数。"""
    return json.dumps(
        [kind, payload.get("prompt"), payload.get("images"), payload.get("raw")],
        ensure_ascii=False,
        sort_keys=True,
    )


def audit_capture(directory: Path) -> CaptureAudit:
    """读取本次独立目录；格式错误显式上抛，不跳过坏文件。"""
    result = CaptureAudit()
    recorded: Counter[str] = Counter()
    for port in sorted((directory / "brain_calls").glob("*/*")):
        coverage = PortCoverage()
        result.ports[port.relative_to(directory / "brain_calls").as_posix()] = coverage
        for request in port.glob("*.request.json"):
            _audit_invocation(request, coverage, recorded)
    traced: Counter[str] = Counter()
    for path in (directory / "trace").glob("*.json"):
        event = json.loads(path.read_text("utf-8"))
        if event["kind"] in KINDS.values():
            payload = event["content"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            traced[_signature(event["kind"], payload)] += 1
    result.trace_attempts = traced.total()
    result.recorded_attempts = recorded.total()
    result.missing_from_recording = (traced - recorded).total()
    result.missing_from_trace = (recorded - traced).total()
    return result


def _audit_invocation(request: Path, coverage: PortCoverage, recorded: Counter[str]) -> None:
    """一个完整工具调用可对应多次模型尝试；反思可能不调用模型。"""
    coverage.requests += 1
    prefix = request.name.removesuffix(".request.json")
    parent = request.parent
    ending = parent / f"{prefix}.end.json"
    if not ending.exists():
        coverage.pending += 1
    else:
        end = json.loads(ending.read_text("utf-8"))
        coverage.elapsed_s += end["elapsed_s"]
    response = parent / f"{prefix}.response.json"
    failure = parent / f"{prefix}.failure.json"
    if response.exists():
        coverage.successes += 1
        saved = json.loads(response.read_text("utf-8"))
    elif failure.exists():
        coverage.failures += 1
        saved = json.loads(failure.read_text("utf-8"))
    else:
        return
    calls = saved.get("calls", [])
    coverage.model_attempts += len(calls)
    if calls:
        kind = KINDS[parent.name]
        for call in calls:
            payload = call["payload"]
            if "started_at" in payload and "ended_at" in payload:
                coverage.model_elapsed_s += float(payload["ended_at"]) - float(
                    payload["started_at"]
                )
            recorded[_signature(kind, call["payload"])] += 1
