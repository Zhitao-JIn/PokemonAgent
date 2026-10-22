"""进程内序号 `next_seq` 与"同刻按 append 序决胜"的用法示范。

**为什么这个文件值钱**：`seq` 是 `ended_at` 平局时的唯一决胜键，而它是**全局状态**
（进程内一个计数器，两个后端共享）。0928 那条事故——`node_io` 流序断言概率性炸
——根因就是决胜键落在随机 uuid 上。这一组把"严格递增、线程安全、跨实例共享、
同刻按 append 序"四件事分别钉住。

**不经 `TraceTool`**：直接对 `LocalTrace` 与 `next_seq` 说话。门面那半边
（`TraceTool` 同时参数化 local 与 langfuse）留在 `tests/direct/trace/test_trace_seq.py`。

**不 sleep**：需要"同刻"就直接把同一个 `ended_at` 传给每一条。
"""

from __future__ import annotations

import json
import pathlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from _doubles.trace import signed_meta

from pokemon_agent.trace import LocalTrace
from pokemon_agent.trace.seq import next_seq


def test_next_seq_is_positive_and_strictly_increasing() -> None:
    """取号严格递增且为正——它是"第几条"，不是时间戳。"""
    values = [next_seq() for _ in range(100)]

    assert all(value > 0 for value in values)
    assert all(left < right for left, right in zip(values, values[1:], strict=False))


def test_next_seq_hands_out_unique_values_across_threads() -> None:
    """8 线程 × 500 次取号，4000 个值一个不重——计数器自己带锁。"""
    threads, per_thread = 8, 500
    with ThreadPoolExecutor(max_workers=threads) as pool:
        batches = list(pool.map(lambda _: [next_seq() for _ in range(per_thread)], range(threads)))

    values = [value for batch in batches for value in batch]

    assert len(values) == threads * per_thread
    assert len(set(values)) == len(values)


def test_seq_is_process_wide_not_per_instance(tmp_path: pathlib.Path) -> None:
    """两个实例交替写，`seq` 仍是一条线——它不属于任何实例。"""
    first = LocalTrace(root=tmp_path)
    second = LocalTrace(root=tmp_path)

    for step in range(6):
        (first if step % 2 == 0 else second).append(
            "lifecycle", "advance_step", signed_meta(step=step), {}
        )

    sequences = [event.seq for event in first.read_events()]

    assert len(sequences) == 6
    assert len(set(sequences)) == 6
    assert all(left < right for left, right in zip(sequences, sequences[1:], strict=False))


def test_two_instances_break_equal_end_times_by_process_append_order(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个实例共用一个落盘根、交替写八笔**同刻**账，读回顺序就是写入顺序。

    这是 `tests/direct/trace/test_trace_seq.py` 的 local 半边：不经 `TraceTool`，
    直接看 `seq` 有没有把平局掰成执行序。

    **为什么要把 `time.time` 钉在同一毫秒**：文件名是 v7 uuid，最高 48 位就是
    写入时刻的毫秒数。真实时钟下相邻两笔相隔 1~2 ms，那串前缀本身已经替 uuid
    排好序——"决胜键退回 uuid"的 mutant 也能读回写入序，用例就被掩盖成绿的。
    钉死到同一毫秒后八个 uuid 的时间前缀全同，只剩随机位可比，`(ended_at, uuid)`
    才会真的把顺序翻掉。`ended_at` 仍然显式传同一个值（不靠默认时钟）。
    """
    monkeypatch.setattr("pokemon_agent.trace.store.time.time", lambda: 1_000_000.123)

    first = LocalTrace(root=tmp_path)
    second = LocalTrace(root=tmp_path)

    for step in range(8):
        (first if step % 2 == 0 else second).append(
            "lifecycle",
            "advance_step",
            signed_meta(step=step),
            {},
            started_at=12345.0,
            ended_at=12345.0,
        )

    events = first.read_events()

    assert [event.ended_at for event in events] == [12345.0] * 8
    assert [json.loads(event.meta)["step"] for event in events] == list(range(8))
    sequences = [event.seq for event in events]
    assert len(set(sequences)) == 8
    assert all(left < right for left, right in zip(sequences, sequences[1:], strict=False))
