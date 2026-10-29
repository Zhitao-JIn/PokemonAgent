"""真 memory server 的共用内存传输夹具，不占用端口、不调用真实模型。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from pokemon_agent.mcp_servers import memory_server
from pokemon_agent.mcpclient.client import McpClient
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.memory_tool import MemoryMcpTool
from pokemon_agent.memory.recall import MemoryCapability
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
)
from pokemon_agent.schemas.memory import ActMemory


class Embedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]


class Reranker:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0 for _ in documents]


class InMemoryClient(McpClient):
    """仅替换传输；同步门面、线程循环和 SDK tool 调用均用真实实现。"""

    async def _call_remote_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with create_connected_server_and_client_session(
            memory_server.mcp._mcp_server
        ) as session:
            await session.initialize()
            if name == "__list_tools__":
                return {"tools": [tool.name for tool in (await session.list_tools()).tools]}
            result = await session.call_tool(name, arguments)
            assert not result.isError
            if result.structuredContent is not None:
                return dict(result.structuredContent)
            return json.loads(result.content[0].text)


def act(step: int) -> dict[str, Any]:
    observation = ActMemory.Observation(facts={"overlay": "none"}, step=step)
    payload = ActMemory(
        before=observation,
        after=observation,
        action="up",
        step=step,
        run_id="run",
        episode_id="episode",
        observations=[],
        outcome=None,
    ).model_dump()
    return {"kind": "act", "payload": payload}


def recall(tool: MemoryTool) -> list[dict[str, Any]]:
    return [
        item.model_dump()
        for item in tool.recall(
            FromHarnessToMemoryToolRecallReq(
                query="", conditions={"episode_id": "episode"}, limit=20
            )
        ).items
    ]


@contextmanager
def memory_server_context(
    memory_root: Path | None,
    snapshot_root: Path,
) -> Iterator[tuple[MemoryCapability, MemoryTool]]:
    """临时注入真能力与内存传输，退出时关闭客户端并恢复服务端全局；不可并行。"""
    with pytest.MonkeyPatch.context() as patch:
        server_instance = FastMCP("test-memory")
        server_instance.tool()(memory_server.recall)
        server_instance.tool()(memory_server.memorize)
        server_instance.custom_route("/health", methods=["GET"])(memory_server.health)
        patch.setattr(memory_server, "mcp", server_instance)
        patch.setattr(memory_server, "_capability", None)
        server = MemoryCapability(Embedder(), Reranker(), memory_root=memory_root)
        memory_server.start(server)
        client = InMemoryClient("in-memory")
        try:
            client.start()
            yield server, MemoryTool(MemoryMcpTool(client))
        finally:
            client.stop()


@pytest.fixture
def remote(tmp_path: Path) -> Iterator[tuple[MemoryCapability, MemoryTool]]:
    """每例隔离服务端记忆根与客户端快照根。"""
    with memory_server_context(tmp_path / "server", tmp_path / "client") as connected:
        yield connected
