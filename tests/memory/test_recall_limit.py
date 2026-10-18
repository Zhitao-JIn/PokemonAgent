"""召回上限由调用方决定；MCP 的默认上限保持为 8。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from _doubles.memory_server import Embedder, Reranker, act, memory_server_context
from mcp.shared.memory import create_connected_server_and_client_session

from pokemon_agent.mcp_servers import memory_server
from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.harness import FromHarnessToMemoryToolRecallReq
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory


@pytest.fixture
def capability(tmp_path: Path) -> MemoryCapability:
    """两条 hint act、十条 episode、十条 knowledge，融合共 22 条。"""
    memory = MemoryCapability(Embedder(), Reranker(), tmp_path)
    records = [act(1), act(2)]
    for index in range(10):
        episode = EpisodeMemory(
            run_id=f"run{index}",
            episode_id="episode",
            goal="field",
            steps=1,
            summary="field",
            markdown="field",
            quality_score=0.5,
            quality_rationale="example",
        )
        records.extend(
            [
                {"kind": "episode", "payload": episode.model_dump()},
                {
                    "kind": "knowledge",
                    "payload": {
                        "topic": str(index),
                        "text": "field",
                        "source": "example",
                        "run_id": "run",
                        "episode_id": "episode",
                    },
                },
            ]
        )
    memory.memorize(records)
    return memory


@pytest.mark.parametrize("explicit_none", [False, True])
def test_unlimited_recall_keeps_every_fused_item(
    capability: MemoryCapability, explicit_none: bool
) -> None:
    arguments: dict[str, Any] = {"limit": None} if explicit_none else {}

    items = capability.recall("field", {"episode_id": "episode"}, **arguments)

    assert len(items) == 22
    assert [item["kind"] for item in items] == ["act"] * 2 + ["episode"] * 10 + ["knowledge"] * 10


def test_integer_limit_cuts_after_fusion_and_preserves_hint_order(
    capability: MemoryCapability,
) -> None:
    all_items = capability.recall("field", {"episode_id": "episode"}, limit=None)

    items = capability.recall("field", {"episode_id": "episode"}, limit=3)

    assert items == all_items[:3]
    assert [item["kind"] for item in items] == ["act", "act", "episode"]
    assert [item["payload"]["step"] for item in items[:2]] == [1, 2]


@pytest.mark.parametrize("limit, expected", [(None, 10), (3, 3)])
def test_run_only_recall_respects_optional_limit(
    tmp_path: Path, limit: int | None, expected: int
) -> None:
    capability = MemoryCapability(Embedder(), Reranker(), tmp_path)
    records = [
        {
            "kind": "run",
            "payload": RunMemory(
                run_id=f"r{index}",
                run_goal="field",
                episodes=0,
                succeeded=0,
                summary="",
                quality_score=0.5,
                quality_rationale="example",
            ).model_dump(),
        }
        for index in range(10)
    ]
    capability.memorize(records)

    items = capability.recall("", {"runs": "all"}, limit=limit)

    assert len(items) == expected
    assert [item["payload"]["run_id"] for item in items] == [f"r{i}" for i in range(expected)]


def test_recall_request_keeps_default_and_accepts_none() -> None:
    assert FromHarnessToMemoryToolRecallReq().limit == 8
    assert FromHarnessToMemoryToolRecallReq(limit=None).limit is None
    with pytest.raises(ValueError):
        FromHarnessToMemoryToolRecallReq(limit=0)


def test_mcp_default_is_eight_and_null_keeps_all(tmp_path: Path) -> None:
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (capability, tool):
        capability.memorize([act(step) for step in range(10)])

        default = tool.recall(
            FromHarnessToMemoryToolRecallReq(conditions={"episode_id": "episode"})
        )
        unlimited = tool.recall(
            FromHarnessToMemoryToolRecallReq(conditions={"episode_id": "episode"}, limit=None)
        )
        direct_default, direct_null = asyncio.run(_server_limits())

        assert len(default.items) == len(direct_default) == 8
        assert len(unlimited.items) == len(direct_null) == 10


async def _server_limits() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """直接通过 MCP 省略 limit，避免客户端默认值掩盖服务端默认值。"""
    async with create_connected_server_and_client_session(memory_server.mcp._mcp_server) as session:
        await session.initialize()
        results: list[list[dict[str, Any]]] = []
        for arguments in ({}, {"limit": None}):
            response = await session.call_tool(
                "recall", {"query": "", "conditions": {"episode_id": "episode"}, **arguments}
            )
            assert not response.isError
            results.append(json.loads(response.content[0].text)["data"]["items"])
        return results[0], results[1]
