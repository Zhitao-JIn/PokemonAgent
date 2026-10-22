"""`TracePort` 契约的用法示范：换一个实现，同一批断言照样跑。

**为什么这个文件值钱**：`TracePort` 是 trace 对外的全部承诺——`append` 返回什么、
读回按什么排、`meta` 筛选是交集还是并集、缺键算不算命中。这些语义没有编译器保护，
换实现就得重证一遍；写成"夹具产出实现、用例只经四个方法说话"的形状，Langfuse
阶段只需往夹具的 `params` 里加一项和一个构造分支，用例一行不改。

**这里不读盘、不碰 `tmp_path` 里的文件**：可观察通道只有公开返回值与读回的 `Event`。
落盘形状、残文件容忍那些"本地实现特有"的行为归 `tests/trace/local/`。

**离线**：`LocalTrace(root=tmp_path)`，不连网、不碰模拟器、不调模型。
"""

from __future__ import annotations

import json
import pathlib

import pytest
from _doubles.trace import signed_meta

from pokemon_agent.trace import LocalTrace, TracePort


@pytest.fixture(params=["local"])
def trace(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> TracePort:
    """按 `params` 造一个实现，用例只经 `TracePort` 说话。

    本轮只有 `LocalTrace`（Langfuse 整体放到 trace 线最后一个阶段）；加实现时
    在这里多一个分支，用例不动。
    """
    assert request.param == "local", f"未知实现：{request.param}"
    return LocalTrace(root=tmp_path)


def test_the_implementation_satisfies_the_trace_port_protocol(trace: TracePort) -> None:
    """实现必须结构化满足 `TracePort`——四个方法齐了才算一个后端。"""
    assert isinstance(trace, TracePort)


def test_append_returns_the_uuid_of_the_event_it_stored(trace: TracePort) -> None:
    """`append` 交回的是**这一条事件**的本地 uuid，不是后端 observation id。"""
    stored = trace.append("lifecycle", "advance_step", signed_meta(), {})

    (event,) = trace.read_events()

    assert isinstance(stored, str) and stored, "uuid 必须是非空字符串"
    assert event.uuid == stored, "返回值要和读回事件的 uuid 是同一个"


def test_two_appends_get_two_distinct_uuids(trace: TracePort) -> None:
    """两条事件的标识不许撞——文件名、按 id 对账都靠它。"""
    first = trace.append("lifecycle", "advance_step", signed_meta(step=0), {})
    second = trace.append("lifecycle", "advance_step", signed_meta(step=1), {})

    assert first != second


def test_an_empty_trace_reads_as_an_empty_list(trace: TracePort) -> None:
    """一条都没写过时读回空列表，不抛异常。"""
    assert trace.read_events() == []


def test_reading_without_a_filter_returns_every_event(trace: TracePort) -> None:
    """`None` 与空 dict 都等于"不过滤"——两种写法都得被当成没有条件。"""
    trace.append("lifecycle", "advance_step", signed_meta(step=0), {})
    trace.append("lifecycle", "advance_step", signed_meta(step=1), {})

    assert len(trace.read_events()) == 2
    assert len(trace.read_events({})) == 2


def test_filter_requires_every_given_key_to_match(trace: TracePort) -> None:
    """给了多个键时**每个键都要相等**：只命中一个键的事件不算命中。"""
    first = trace.append("lifecycle", "advance_step", signed_meta(run_id="run-a"), {})
    second = trace.append("lifecycle", "advance_step", signed_meta(run_id="run-b"), {})

    assert [e.uuid for e in trace.read_events({"run_id": "run-a"})] == [first]
    assert [e.uuid for e in trace.read_events({"run_id": "run-b"})] == [second]

    assert [e.uuid for e in trace.read_events({"run_id": "run-a", "step": 0})] == [first]
    assert [e.uuid for e in trace.read_events({"run_id": "run-a", "branch": "main"})] == [first]


def test_filter_is_and_not_or(trace: TracePort) -> None:
    """交集为空就是空列表，不是"命中任意一个"。

    两条账各被一个条件命中、但没有任何一条同时满足两个条件——写成 OR 的话
    这里会返回两条。
    """
    trace.append("lifecycle", "advance_step", signed_meta(run_id="run-a", episode_id="ep-1"), {})
    trace.append("lifecycle", "advance_step", signed_meta(run_id="run-b", episode_id="ep-2"), {})

    assert len(trace.read_events({"run_id": "run-a"})) == 1
    assert len(trace.read_events({"episode_id": "ep-2"})) == 1
    assert trace.read_events({"run_id": "run-a", "episode_id": "ep-2"}) == []


def test_an_event_missing_a_filtered_key_never_matches(trace: TracePort) -> None:
    """缺键**不等于**空值：连空串条件都捞不出缺该键的事件。"""
    trace.append("lifecycle", "advance_step", signed_meta(), {})
    trace.append("lifecycle", "advance_step", {"run_id": "run-1", "branch": "main"}, {})

    assert trace.read_events({"episode_id": ""}) == [], "缺键与空值必须分开"
    assert trace.read_events({"不存在的键": "x"}) == []


def test_filter_compares_values_by_equality_including_type(trace: TracePort) -> None:
    """等值比较带类型：盘上存的是整数 `3`，问字符串 `"3"` 不算命中。"""
    trace.append("lifecycle", "advance_step", signed_meta(step=3), {})

    assert len(trace.read_events({"step": 3})) == 1
    assert trace.read_events({"step": "3"}) == []


def test_a_filter_that_matches_nothing_returns_an_empty_list_without_raising(
    trace: TracePort,
) -> None:
    """没匹配上就是空表——筛选不是"找不到就报错"。"""
    trace.append("lifecycle", "advance_step", signed_meta(), {})

    assert trace.read_events({"run_id": "不存在的 run"}) == []


def test_events_are_returned_ordered_by_ended_at(trace: TracePort) -> None:
    """读回按 `ended_at` 升序——先做完的排前面，与写入顺序无关。"""
    later = trace.append(
        "lifecycle", "advance_step", signed_meta(step=2), {}, ended_at=300.0, started_at=299.0
    )
    earliest = trace.append(
        "lifecycle", "advance_step", signed_meta(step=0), {}, ended_at=100.0, started_at=99.0
    )
    middle = trace.append(
        "lifecycle", "advance_step", signed_meta(step=1), {}, ended_at=200.0, started_at=199.0
    )

    assert [e.uuid for e in trace.read_events()] == [earliest, middle, later]
    assert [e.ended_at for e in trace.read_events()] == [100.0, 200.0, 300.0]


def test_equal_ended_at_is_broken_by_append_order(trace: TracePort) -> None:
    """同刻账按 append 序决胜——`ended_at` 平局时不许退回随机 uuid。

    0928 的事故就是这一条：决胜键落在随机 uuid 上，执行序每次进程洗一次牌。
    """
    same_moment: list[str] = []
    for step in range(4):
        same_moment.append(
            trace.append(
                "lifecycle",
                "advance_step",
                signed_meta(step=step),
                {},
                started_at=12345.0,
                ended_at=12345.0,
            )
        )

    events = trace.read_events()

    assert [e.uuid for e in events] == same_moment
    assert [json.loads(e.meta)["step"] for e in events] == [0, 1, 2, 3]


def test_meta_and_content_decode_back_to_the_original_objects(trace: TracePort) -> None:
    """`meta` / `content` 是 JSON 字符串，`json.loads` 回来必须**无损**（含中文与 `None`）。"""
    meta = signed_meta(source="中文来源")
    content = {"文本": "中文内容", "嵌套": [1, {"深层": "值"}], "空": None}

    trace.append("lifecycle", "advance_step", meta, content)

    (event,) = trace.read_events()

    assert json.loads(event.meta) == meta
    assert json.loads(event.content) == content


def test_flush_and_shutdown_can_be_called_repeatedly_and_events_stay_readable(
    trace: TracePort,
) -> None:
    """`flush` / `shutdown` 都是 `None` 返回、可重复调用，之后账照样读得出。"""
    stored = trace.append("lifecycle", "advance_step", signed_meta(), {})

    assert trace.flush() is None
    assert trace.flush() is None
    assert trace.shutdown() is None
    assert trace.shutdown() is None

    assert [e.uuid for e in trace.read_events()] == [stored]
