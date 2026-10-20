"""Trace 查询的公开用法：等值过滤、尾部翻页、去图，以及正常读取失败。"""

import json
from typing import Any

import pytest

from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.reviewer import FrameQuery, TraceQuery

FRAME = "data:image/png;base64,YQ=="


def event(number: int, run_id: str = "r1", *, kind: str = "sense_frame") -> TraceEvent:
    return TraceEvent(
        uuid=f"id{number}",
        seq=number,
        kind=kind,
        type="view",
        started_at=1,
        ended_at=2,
        meta=json.dumps(
            {
                "run_id": run_id,
                "episode_id": "e1",
                "task_id": "t1",
                "source": "perceive",
                "step": number,
            }
        ),
        content=json.dumps({"number": number, "frame": FRAME, "nested": [{"other": FRAME}]}),
    )


class Trace:
    def __init__(self, events: list[TraceEvent]) -> None:
        self.events = events
        self.requests: list[dict[str, Any]] = []

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        self.requests.append(dict(meta or {}))
        return [
            event
            for event in self.events
            if all(json.loads(event.meta).get(k) == v for k, v in (meta or {}).items())
        ]


def test_trace_filters_before_paging_and_preserves_the_readers_event_list() -> None:
    trace = Trace([event(5), event(9, kind="do_action"), event(1), event(3), event(99, "other")])
    before = [item.model_dump_json() for item in trace.events]
    readers = ViewReaders(trace, None, trace_delayed=True)

    answer = readers.read_trace(
        TraceQuery(
            episode_id="e1", task_id="t1", source="perceive", kind="sense_frame", last_n=2, offset=1
        ),
        default_run_id="r1",
    )

    assert answer.ok and not answer.images
    assert trace.requests == [
        {"run_id": "r1", "episode_id": "e1", "task_id": "t1", "source": "perceive"}
    ]
    assert '"number": 1' in answer.text and '"number": 3' in answer.text
    assert '"number": 5' not in answer.text and '"number": 9' not in answer.text
    assert answer.text.index('"number": 1') < answer.text.index('"number": 3')
    assert "可能不含最近几秒" in answer.text
    assert "[frame omitted]" in answer.text and "data:" not in answer.text
    assert [item.model_dump_json() for item in trace.events] == before


def test_explicit_run_can_read_another_run_and_offset_can_exhaust_the_page() -> None:
    trace = Trace([event(1), event(2, "other")])
    readers = ViewReaders(trace, None)

    answer = readers.read_trace(TraceQuery(run_id="other"), default_run_id="r1")
    empty = readers.read_trace(TraceQuery(offset=100), default_run_id="r1")

    assert '"number": 2' in answer.text and '"number": 1' not in answer.text
    assert "返回 0 条" in empty.text and empty.ok


@pytest.mark.parametrize("limit", [0, 5, 300])
def test_trace_removes_data_uris_before_content_truncation(limit: int) -> None:
    trace = Trace([event(1)])
    answer = ViewReaders(trace, None).read_trace(
        TraceQuery(content_limit=limit), default_run_id="r1"
    )

    body = answer.text.splitlines()[1].split(" · ")[-1]
    assert len(body) <= limit + bool(limit)
    assert "data:" not in answer.text and "YQ==" not in answer.text


def test_latest_uses_the_newest_sense_frame_not_an_action_or_another_run() -> None:
    trace = Trace([event(4, kind="do_action"), event(1), event(3), event(9, "other")])

    answer = ViewReaders(trace, None).read_frame(FrameQuery(which="latest"), default_run_id="r1")

    assert answer.ok and answer.images == [FRAME]
    assert "id3" in answer.text and "data:" not in answer.text


@pytest.mark.parametrize("content", ["{}", '{"frame": "bad"}', "[]", "{bad"])
def test_latest_missing_or_malformed_frame_does_not_fall_back_to_an_older_frame(
    content: str,
) -> None:
    latest = event(2).model_copy(update={"content": content})

    answer = ViewReaders(Trace([event(1), latest]), None).read_frame(
        FrameQuery(which="latest"), default_run_id="r1"
    )

    assert not answer.ok and not answer.images


class BrokenTrace:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        raise self.error


@pytest.mark.parametrize("error", [OSError("file"), TimeoutError("timeout"), RuntimeError(FRAME)])
def test_normal_read_failures_return_text_with_no_picture(error: Exception) -> None:
    readers = ViewReaders(BrokenTrace(error), None)

    answer = readers.read_trace(TraceQuery(), default_run_id="r1")

    assert not answer.ok and not answer.images and "data:" not in answer.text


def test_programming_errors_are_not_hidden_as_query_failures() -> None:
    with pytest.raises(TypeError, match="bug"):
        ViewReaders(BrokenTrace(TypeError("bug")), None).read_trace(
            TraceQuery(), default_run_id="r1"
        )


def test_unconfigured_ports_and_absent_frames_are_explicit_failures() -> None:
    readers = ViewReaders(None, None)

    assert readers.read_trace(TraceQuery(), default_run_id="r1").text == "读端口未接入"
    assert (
        readers.read_frame(FrameQuery(which="latest"), default_run_id="r1").text == "读端口未接入"
    )
    assert (
        not ViewReaders(Trace([]), None)
        .read_frame(FrameQuery(which="latest"), default_run_id="r1")
        .ok
    )
