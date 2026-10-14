"""同刻事件在两个后端实例之间仍按进程内 append 次序排序。"""

import json
from pathlib import Path

import pytest
from _fake_langfuse import FakeLangfuseClient

from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.trace import LangfuseTrace, LocalTrace


@pytest.mark.parametrize("backend", ["local", "langfuse"])
def test_two_trace_tools_break_equal_end_times_by_process_append_order(
    tmp_path: Path, backend: str
):
    if backend == "local":
        first_backend, second_backend = LocalTrace(root=tmp_path), LocalTrace(root=tmp_path)
    else:
        client = FakeLangfuseClient()
        trace_id = client.create_trace_id(seed="run")
        first_backend = LangfuseTrace(trace_id=trace_id, client=client)
        second_backend = LangfuseTrace(trace_id=trace_id, client=client)
    first = TraceTool(first_backend, run_id="run", branch="main")
    second = TraceTool(second_backend, run_id="run", branch="b1")

    for step, tool in enumerate((first, second, first, second)):
        tool.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.READ_ACT_MEMORY,
                meta={"source": "test", "episode_id": "episode", "task_id": "task", "step": step},
                query="episode_id=episode",
                refs=[],
                started_at=12345.0,
                ended_at=12345.0,
            )
        )

    events = first.read_events({})
    assert [event.ended_at for event in events] == [12345.0] * 4
    assert [json.loads(event.meta)["step"] for event in events] == [0, 1, 2, 3]
    sequences = [event.seq for event in events]
    assert len(set(sequences)) == 4
    assert all(left < right for left, right in zip(sequences, sequences[1:], strict=False))
