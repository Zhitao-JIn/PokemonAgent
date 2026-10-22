"""事件形状与词表的机械守卫：`Event` 协议 ↔ 盘上记录 ↔ `EventType` 常量。

**为什么这个文件值钱**：这条契约是三份定义靠人工同步维系的——`Event` 协议
（`trace/interface/event.py`）、`_Event` 实现（`trace/datastore/event.py`）、项目侧的
`TraceEvent`（`schemas/harness/domain/`）。**没有编译器保护**：字段对不上不会报错，
只会静默丢字段。这里用"协议声明的属性名集合 == 一条真实落盘记录的键集合"把
对齐从声明变成可执行的事实；项目侧那一半（`TraceEvent`）在
`tests/direct/trace/test_trace_event_alignment.py`，因为它要 import `schemas/`。

**词表那两条守的是同一件事的两种表达**：`EventType` 是常量类，`EventTypeName` 是
`Literal`，两处人工同步，没有代码把它们绑在一起。

**离线**：落盘根用 `tmp_path`，不连网、不碰模拟器、不调模型。
"""

from __future__ import annotations

import json
import pathlib
import typing

from _doubles.trace import signed_meta

from pokemon_agent.trace import Event, LocalTrace
from pokemon_agent.trace.datastore import EventType
from pokemon_agent.trace.datastore.trace_event import EventTypeName


def _written_record(tmp_path: pathlib.Path) -> dict[str, object]:
    """写一笔最短的账，把盘上那份 json 原样解回来。"""
    LocalTrace(root=tmp_path).append("lifecycle", "advance_step", signed_meta(), {})

    (path,) = tmp_path.glob("*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_event_protocol_declares_exactly_the_fields_stored_on_disk(
    tmp_path: pathlib.Path,
) -> None:
    """`Event` 声明的属性名 == 一条落盘记录的键集合（八个别多别少）。"""
    declared = set(Event.__annotations__)
    on_disk = set(_written_record(tmp_path))

    assert declared == on_disk, (
        f"协议有、盘上没有：{sorted(declared - on_disk)}；"
        f"盘上有、协议没有：{sorted(on_disk - declared)}"
    )


def test_event_type_constants_are_the_seven_documented_strings() -> None:
    """`EventType` 的公开常量就是文档里那七个字符串——不多不少。"""
    constants = {name: value for name, value in vars(EventType).items() if not name.startswith("_")}

    assert set(constants.values()) == {
        "model_call",
        "error",
        "llm_outcome",
        "view",
        "act",
        "memory_io",
        "lifecycle",
    }
    assert len(constants) == 7


def test_event_type_name_literal_covers_exactly_the_event_type_constants() -> None:
    """`Literal` 的成员与常量类的取值同一集合——两处人工同步的机械版。"""
    literal_values = set(typing.get_args(EventTypeName))
    constant_values = {value for name, value in vars(EventType).items() if not name.startswith("_")}

    assert literal_values == constant_values
