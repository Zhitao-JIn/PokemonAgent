"""跨局摘要的读口用法示范（`MemoryTool.query_episode_summaries`，存储是真的，模型换成桩）。

按元数据等值筛出本 run 的各局摘要；返回顺序由读口自己定——按 `episode_id` 的自然序
（`ep2` < `ep10`），即执行顺序。调用方不传排序参数，也不在拿到结果后再排。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _doubles.memory_server import memory_server_context

from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)
from pokemon_agent.schemas.memory import EpisodeMemory


@pytest.fixture
def memory(tmp_path: Path) -> Iterator[MemoryTool]:
    """通过内存传输连接真 memory server。"""
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (_, tool):
        yield tool


def _summary(episode_id: str) -> EpisodeMemory:
    return EpisodeMemory(
        episode_id=episode_id,
        run_id="r1",
        goal="g",
        steps=1,
        summary="",
        quality_score=0.0,
        quality_rationale="-",
    )


def test_episode_summaries_come_back_in_execution_order(memory: MemoryTool) -> None:
    """写入顺序打乱，读回来仍是第 1、2、…、12 局：第 10 局排在第 2 局之后（字典序会反过来）。"""
    for n in (10, 2, 12, 1, 11, 3, 9, 4, 8, 5, 7, 6):
        memory.memorize(
            FromHarnessToMemoryToolMemorizeReq(
                records=[
                    FromHarnessToMemoryToolMemorizeRecord(
                        kind="episode", payload=_summary(f"r1-ep{n}").model_dump()
                    )
                ]
            )
        )
    resp = memory.recall(
        FromHarnessToMemoryToolRecallReq(query="", conditions={"run_id": "r1"}, limit=10**6)
    )
    got = [
        EpisodeMemory(**item.payload, markdown=item.content)
        for item in resp.items
        if item.kind == "episode"
    ]
    assert [m.episode_id for m in got] == [f"r1-ep{n}" for n in range(1, 13)]
