"""run 三本账的真实渲染、落盘与类型化读回。"""

from pathlib import Path

from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.direct.trace.content import (
    ModelCallContent,
    ReadRunMemoryContent,
    WriteRunMemoryContent,
)
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, ModelCall, TraceKind
from pokemon_agent.schemas.memory import RunMemory


def test_run_memory_trace_round_trips_three_registered_kinds(tmp_path: Path) -> None:
    trace = TraceTool.build(run_id="r1", trace_root=tmp_path)
    meta = {"source": "run.summarize_run", "episode_id": "r1", "task_id": "r1", "step": 1}
    memory = RunMemory(
        run_id="r1",
        run_goal="总目标",
        episodes=1,
        succeeded=1,
        termination="goal_done",
        summary="复盘",
        markdown="复盘",
        quality_score=0.5,
        quality_rationale="q",
    )

    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_RUN_CALL,
            meta=meta,
            calls=[ModelCall(payload={"ok": "true", "prompt": "复盘", "raw": "{}"})],
        )
    )
    trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.WRITE_RUN_MEMORY, meta=meta, memory=memory)
    )
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_RUN_MEMORY, meta=meta, query="runs=all", refs=["r1"]
        )
    )
    events = [parse(event) for event in trace.read_events({})]

    assert isinstance(events[0].content, ModelCallContent)
    assert isinstance(events[1].content, WriteRunMemoryContent)
    assert isinstance(events[2].content, ReadRunMemoryContent)
    assert events[2].content.refs == ["r1"]
    assert not {"run_goal", "run_id", "episodes", "succeeded", "termination", "acts_used"} & set(
        events[1].content.model_dump()
    )
    assert "data:image" not in events[1].content.model_dump_json()
