"""`LocalTrace.read_events` 的读语义：同一落盘根、按 run 切片、只读不改盘。

**为什么这个文件值钱**：落盘根是**平铺**的——一条事件一个 json、没有 run 目录。
"读哪一批"全靠 `meta` 交集，于是"两个实例互相看得见""两个 run 想分就分"
这两条就成了解释"平铺为什么可行"的全部依据。另两条钉的是读方法的纯度：
读不该动盘，读回的对象该满足 `Event` 协议（而不是一堆 dict）。

**离线**：落盘根一律 `tmp_path`。
"""

from __future__ import annotations

import json
import pathlib

from _doubles.trace import signed_meta

from pokemon_agent.trace import Event, LocalTrace


def test_two_instances_on_one_root_see_each_others_events(tmp_path: pathlib.Path) -> None:
    """同一个根上的两个实例读的是同一批文件——`LocalTrace` 不持有内存状态。"""
    first = LocalTrace(root=tmp_path)
    second = LocalTrace(root=tmp_path)

    first.append("lifecycle", "advance_step", signed_meta(step=0), {})
    second.append("lifecycle", "advance_step", signed_meta(step=1), {})

    assert sorted(json.loads(e.meta)["step"] for e in first.read_events()) == [0, 1]
    assert sorted(json.loads(e.meta)["step"] for e in second.read_events()) == [0, 1]


def test_events_of_different_runs_share_the_root_and_are_sliced_by_run_id(
    tmp_path: pathlib.Path,
) -> None:
    """平铺的代价与解法：两个 run 共用一个目录，靠 `meta.run_id` 切片。"""
    store = LocalTrace(root=tmp_path)

    store.append("lifecycle", "advance_step", signed_meta(run_id="run-a"), {})
    store.append("lifecycle", "advance_step", signed_meta(run_id="run-b"), {})
    store.append("lifecycle", "advance_step", signed_meta(run_id="run-a"), {})

    assert [json.loads(e.meta)["run_id"] for e in store.read_events({"run_id": "run-a"})] == [
        "run-a",
        "run-a",
    ]
    assert [json.loads(e.meta)["run_id"] for e in store.read_events({"run_id": "run-b"})] == [
        "run-b"
    ]
    assert len(store.read_events()) == 3, "不筛就是整个落盘根——两个 run 都看得见"


def test_reading_does_not_modify_the_root(tmp_path: pathlib.Path) -> None:
    """读是只读：文件名集合与每个文件的字节，读前读后必须一模一样。"""
    store = LocalTrace(root=tmp_path)
    store.append("lifecycle", "advance_step", signed_meta(step=0), {})
    store.append("lifecycle", "advance_step", signed_meta(step=1), {})

    def snapshot() -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}

    before = snapshot()
    store.read_events()
    store.read_events({"run_id": "run-1"})

    assert snapshot() == before


def test_read_events_return_typed_event_objects(tmp_path: pathlib.Path) -> None:
    """读回的是满足 `Event` 协议的对象，不是裸 dict：类型齐了才谈得上"封套"。

    `meta` / `content` 仍是 **JSON 字符串**（解一层是读方的事），`uuid` 与文件名同值。
    """
    store = LocalTrace(root=tmp_path)

    event_uuid = store.append("lifecycle", "advance_step", signed_meta(), {})

    (path,) = tmp_path.glob("*.json")
    (event,) = store.read_events()

    assert isinstance(event, Event)
    assert isinstance(event.uuid, str)
    assert isinstance(event.seq, int)
    assert isinstance(event.started_at, float)
    assert isinstance(event.ended_at, float)
    assert isinstance(event.meta, str)
    assert isinstance(event.content, str)
    assert event.uuid == path.stem == event_uuid
    assert event.kind == "advance_step"
    assert event.type == "lifecycle"
