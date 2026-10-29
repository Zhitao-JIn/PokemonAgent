"""记忆查询保留跨 run 的探索能力，只在 images 返回帧，允许派生缓存客观刷新。"""

import hashlib
from pathlib import Path

import pytest
from _doubles.memory_server import act, memory_server_context

from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
)
from pokemon_agent.schemas.memory import RunMemory
from pokemon_agent.schemas.reviewer import FrameQuery, RecallQuery

BEFORE = "data:image/png;base64,YmVmb3Jl"
AFTER = "data:image/png;base64,YWZ0ZXI="


class Memory:
    def __init__(self, items: list[FromHarnessToMemoryToolRecallItem]) -> None:
        self.items = items
        self.requests: list[FromHarnessToMemoryToolRecallReq] = []

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        self.requests.append(req)
        return FromHarnessToMemoryToolRecallResp(items=self.items)


def test_recall_forwards_all_hints_without_adding_run_scope_and_removes_images() -> None:
    item = FromHarnessToMemoryToolRecallItem(
        kind="episode",
        uuid="other-run-memory",
        score=0.5,
        content=f"场景 {BEFORE}",
        payload={"run_id": "old-run", "first_frame": BEFORE, "nested": {"photo": AFTER}},
    )
    memory = Memory([item, item, item])
    before = item.model_dump_json()

    answer = ViewReaders(None, memory).recall(
        RecallQuery(query="badge", conditions={"run_goal": "badge"}, limit=2)
    )

    assert memory.requests == [
        FromHarnessToMemoryToolRecallReq(query="badge", conditions={"run_goal": "badge"}, limit=2)
    ]
    assert answer.ok and not answer.images
    assert answer.text.count("other-run-memory") == 2 and "old-run" in answer.text
    assert "data:" not in answer.text and "[frame omitted]" in answer.text
    assert item.model_dump_json() == before


@pytest.mark.parametrize("which, expected", [("before", BEFORE), ("after", AFTER)])
def test_real_mcp_frame_queries_reach_steps_beyond_eight(
    tmp_path: Path, which: str, expected: str
) -> None:
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (
        capability,
        tool,
    ):
        records = [act(step) for step in range(12)]
        for record in records:
            record["payload"].update(before_frame=BEFORE, after_frame=AFTER)
        capability.memorize(records)
        before = {
            str(path): path.read_bytes()
            for path in (tmp_path / "server").rglob("*")
            if path.is_file()
        }

        answer = ViewReaders(None, tool).read_frame(
            FrameQuery(which=which, episode_id="episode", step=11), default_run_id="run"
        )

        assert answer.ok and answer.images == [expected]
        assert "step=11" in answer.text and which in answer.text and "data:" not in answer.text
        assert all(Path(path).read_bytes() == data for path, data in before.items())


def test_runs_all_reaches_the_real_mcp_run_family_without_a_run_filter(tmp_path: Path) -> None:
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (
        capability,
        tool,
    ):
        records = [
            {
                "kind": "run",
                "payload": RunMemory(
                    run_id=name,
                    run_goal="badge",
                    episodes=0,
                    succeeded=0,
                    summary=name,
                    markdown=name,
                    quality_score=0.5,
                    quality_rationale="example",
                    pointers=[],
                    index={"headline": "", "keys": [], "evidence": []},
                ).model_dump(),
            }
            for name in ("old-run", "current-run")
        ]
        capability.memorize(records)

        answer = ViewReaders(None, tool).recall(RecallQuery(conditions={"runs": "all"}))

        assert answer.ok and "old-run" in answer.text and "current-run" in answer.text


def test_recall_may_refresh_derived_caches_but_never_changes_memory_record_text(
    tmp_path: Path,
) -> None:
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (
        capability,
        tool,
    ):
        capability.memorize(
            [
                {
                    "kind": "knowledge",
                    "payload": {
                        "topic": "probe",
                        "text": "field original",
                        "source": "probe",
                        "run_id": "r",
                        "episode_id": "e",
                    },
                }
            ]
        )
        root = tmp_path / "server" / "knowledge_memory"
        record = next(root.glob("*.md"))
        record.write_text(record.read_text(encoding="utf-8") + "\nfield edited\n", encoding="utf-8")
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.iterdir()
            if path.is_file()
        }

        answer = ViewReaders(None, tool).recall(RecallQuery(query="field"))

        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.iterdir()
            if path.is_file()
        }
        assert answer.ok and "field edited" in answer.text
        assert after[record.name] == before[record.name]
        assert {name for name in after if after[name] != before.get(name)} == {
            "index.json",
            "vectors.jsonl",
        }


@pytest.mark.parametrize(
    "payload", [{}, {"before_frame": "invalid"}, {"before_frame": "data:image/png;base64,%%%"}]
)
def test_missing_or_bad_act_frames_return_a_failure(payload: dict) -> None:
    item = FromHarnessToMemoryToolRecallItem(
        kind="act", uuid="a", payload={"episode_id": "e1", "step": 1, **payload}
    )
    memory = Memory([item])

    answer = ViewReaders(None, memory).read_frame(
        FrameQuery(which="before", episode_id="e1", step=1), default_run_id="r1"
    )

    assert not answer.ok and not answer.images
    assert memory.requests[0].limit is None


def test_missing_act_and_unconfigured_memory_are_explicit_failures() -> None:
    q = FrameQuery(episode_id="e1", step=1)

    assert not ViewReaders(None, Memory([])).read_frame(q, default_run_id="r1").ok
    assert ViewReaders(None, None).read_frame(q, default_run_id="r1").text == "读端口未接入"
    assert ViewReaders(None, None).recall(RecallQuery()).text == "读端口未接入"


class OfflineMemory:
    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        raise RuntimeError("MCP disconnected")


def test_disconnected_memory_is_reported_for_text_and_frame_queries() -> None:
    readers = ViewReaders(None, OfflineMemory())

    answer = readers.recall(RecallQuery(query="badge"))
    frame = readers.read_frame(FrameQuery(episode_id="e1", step=1), default_run_id="r1")

    assert not answer.ok and "MCP disconnected" in answer.text
    assert not frame.ok and not frame.images
