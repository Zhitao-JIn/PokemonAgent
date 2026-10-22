"""`new_event_uuid` 的布局与单调性：v7、跨毫秒字典序即时间序、同毫秒不撞名。

**为什么这个文件值钱**：它是事件文件名，也是"`ls` 看着大致有序"的由来。布局错了
不会报错——只会让同一毫秒内生成的两个 id 撞名（丢账），或者让 `ls` 的序与时间无关。
四条分别钉：版本位与变体位、2000 次不重复、跨毫秒字典序、前 48 位真的是毫秒时间戳。

**排序的真源不是它**（`read_events` 看 `(ended_at, seq)`），这里只证明"文件名这一层
没撒谎"。需要固定时刻就 monkeypatch `pokemon_agent.trace.store.time.time`，不 sleep。
"""

from __future__ import annotations

import uuid

import pytest

from pokemon_agent.trace import new_event_uuid
from pokemon_agent.trace import store as trace_store


def test_uuid_has_the_v7_layout() -> None:
    """版本位 7、变体位 `10xx`（8/9/a/b），且 `uuid.UUID` 能解析。"""
    value = new_event_uuid()

    parsed = uuid.UUID(value)

    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
    assert value[14] == "7"
    assert value[19] in "89ab"


def test_two_thousand_uuids_are_all_distinct() -> None:
    """同一毫秒里连造 2000 个（随机段承担区分度），一个都不许重。"""
    values = [new_event_uuid() for _ in range(2000)]

    assert len(set(values)) == len(values)


def test_a_later_millisecond_sorts_after_an_earlier_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """毫秒进了最高位：后一毫秒的 id 按**字典序**排在前一毫秒之后。"""
    monkeypatch.setattr(trace_store.time, "time", lambda: 1_000_000.100)
    earlier = new_event_uuid()

    monkeypatch.setattr(trace_store.time, "time", lambda: 1_000_000.101)
    later = new_event_uuid()

    assert earlier < later


def test_the_first_48_bits_carry_the_millisecond_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """前 12 个十六进制位就是秒 × 1000 取整——时间戳真的在最高位。"""
    moment = 1_000_000.123
    monkeypatch.setattr(trace_store.time, "time", lambda: moment)

    value = new_event_uuid()

    expected_ms = int(moment * 1000)
    hex_digits = value.replace("-", "")  # 去掉分组连字符，剩下的才是位
    assert hex_digits[:12] == f"{expected_ms:012x}"
    assert uuid.UUID(value).int >> 80 == expected_ms
