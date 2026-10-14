"""跨局摘要的读口用法示范（`MemoryTool.query_episode_summaries`，存储是真的，模型换成桩）。

按元数据等值筛出本 run 的各局摘要；返回顺序由读口自己定——按 `episode_id` 的自然序
（`ep2` < `ep10`），即执行顺序。调用方不传排序参数，也不在拿到结果后再排。
"""

from __future__ import annotations

import pathlib

import pytest

from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)
from pokemon_agent.schemas.memory import EpisodeMemory


class _Embedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0] for _ in texts]


class _Reranker:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0 for _ in documents]


@pytest.fixture
def memory(tmp_path: pathlib.Path) -> MemoryTool:
    """真 `MemoryTool`，记忆根指到 `tmp_path`。"""
    return MemoryTool(
        embedding_provider=_Embedder(),  # type: ignore[arg-type]
        reranker_provider=_Reranker(),  # type: ignore[arg-type]
        memory_root=tmp_path,
    )


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
