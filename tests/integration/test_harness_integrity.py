"""真实三图的完整性集成测试：mock 三件套、真实 trace 与记忆落盘核对。"""

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from _harness_fixtures import node_io
from _harness_fixtures.harness import GOAL, build_fake, never
from pydantic import BaseModel, Field

from pokemon_agent.env import load_env_file


class IntegrityRun(BaseModel):
    """集成核对的问题、账本数量与落盘记忆数量。"""

    problems: list[str] = Field(default_factory=list)
    events: int = 0
    memories: int = 0


def check_events(events: list[dict]) -> None:
    """与已有 node_io 集成测试同一套完整核对。"""
    node_io.check_run_markers(events)
    node_io.check_vocabulary(events)
    node_io.check_payloads(events)
    node_io.check_layer_flow(events)
    node_io.check_run_invariants(events)
    for episode_id in node_io.episode_ids(events):
        node_io.check_node_coverage(events, episode_id)
        node_io.check_content_invariants(events, episode_id)


def run_integrity(root: Path, backend: str, scenario: str) -> IntegrityRun:
    """跑确定性剧本；真实后端 flush 后读回，Langfuse 最多等 10 秒可见。"""
    run_id = f"integrity-{uuid.uuid4()}"
    kwargs = {"task": never} if scenario == "budget" else {}
    fake = build_fake(root, run_id=run_id, backend=backend, **kwargs)
    try:
        fake.harness.run(run_id, [GOAL])
        fake.trace.flush()
        events: list[dict] = []
        for attempt in range(11):
            events = [
                json.loads(event.model_dump_json())
                for event in fake.trace.read_events({"run_id": run_id})
            ]
            if any(event["kind"] == "run_end" for event in events) or backend == "local":
                break
            if attempt < 10:
                time.sleep(1)
        problems: list[str] = []
        try:
            check_events(events)
        except AssertionError as exc:
            problems.append(str(exc))
        records = list((root / "memory_snapshots" / "records").glob("*.json"))
        expected = (
            len(fake.memory.acts)
            + len(fake.memory.tasks)
            + len(fake.memory.episodes)
            + len(fake.memory.runs)
        )
        if len(records) != expected or expected == 0:
            problems.append(f"记忆落盘 {len(records)}，期望 {expected}")
        for record in records:
            json.loads(record.read_text(encoding="utf-8"))
        return IntegrityRun(problems=problems, events=len(events), memories=len(records))
    finally:
        fake.trace.shutdown()


@pytest.mark.parametrize(
    "backend",
    [
        "local",
        pytest.param(
            "langfuse",
            marks=pytest.mark.skipif(
                os.environ.get("TEST_LANGFUSE") != "1",
                reason="显式 TEST_LANGFUSE=1 时验证真实 Langfuse 后端",
            ),
        ),
    ],
)
@pytest.mark.parametrize("scenario", ["normal", "budget"])
def test_real_three_graphs_write_trace_and_memory_with_mock_dependencies(
    tmp_path: Path, backend: str, scenario: str
) -> None:
    load_env_file()

    run = run_integrity(tmp_path, backend, scenario)

    assert not run.problems
    assert run.events > 0 and run.memories > 0
