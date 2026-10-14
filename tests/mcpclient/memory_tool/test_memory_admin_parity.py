"""MemoryTool 的两种传输以同一组操作恢复相同记录，快照跨根传递。"""

from __future__ import annotations

import json
import shutil
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
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
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


def capability(root: Path) -> MemoryCapability:
    return MemoryCapability(Embedder(), Reranker(), memory_root=root)


def act(step: int) -> dict[str, Any]:
    observation = ActMemory.Observation(step=step, status="field")
    payload = ActMemory(
        before=observation,
        after=observation,
        action="up",
        step=step,
        run_id="run",
        episode_id="episode",
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


@pytest.fixture
def remote(tmp_path: Path, monkeypatch):
    server_instance = FastMCP("test-memory")
    server_instance.tool()(memory_server.recall)
    server_instance.tool()(memory_server.memorize)
    server_instance.custom_route("/health", methods=["GET"])(memory_server.health)
    monkeypatch.setattr(memory_server, "mcp", server_instance)
    monkeypatch.setattr(memory_server, "_admin_enabled", False)
    monkeypatch.setattr(memory_server, "_capability", None)
    server = capability(tmp_path / "server")
    memory_server.start(server, enable_admin=True)
    client = InMemoryClient("in-memory")
    client.start()
    delegate = MemoryMcpTool(client, snapshot_root=tmp_path / "client")
    try:
        yield server, client, delegate, MemoryTool._from_delegate(delegate)
    finally:
        client.stop()
        memory_server.start(server)


def test_same_port_operations_restore_the_same_records_and_files(tmp_path: Path, remote):
    seed = capability(tmp_path / "seed")
    seed.memorize([act(1)])
    server, _, _, remote_tool = remote
    shutil.copytree(seed.root, server.root, dirs_exist_ok=True)
    for store in server._stores.values():
        store.reload()
    shutil.copytree(seed.root, tmp_path / "local")
    local = MemoryTool(Embedder(), Reranker(), memory_root=tmp_path / "local")

    results = []
    for tool, root in ((local, tmp_path / "local"), (remote_tool, server.root)):
        snapshot = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="a"))
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(9)]))
        restored = tool.restore_memory(
            FromHarnessToMemoryToolRestoreMemoryReq(archive=snapshot.archive)
        )
        files = {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and "snapshots" not in path.relative_to(root).parts
        }
        results.append((restored.unpacked, recall(tool), files))
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
        assert len(recall(tool)) == 2

    assert results[0] == results[1]
    assert len(results[0][1]) == 1


def test_snapshot_crosses_roots_and_restores_from_an_arbitrary_path(tmp_path: Path, remote):
    server, _, delegate, tool = remote
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    before = recall(tool)

    archive = delegate.snapshot("a")
    external = tmp_path / "elsewhere" / "other.zip"
    external.parent.mkdir()
    shutil.copy2(archive, external)
    delegate.snapshot("a")
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
    unpacked = delegate.restore(external)

    assert archive == tmp_path / "client" / "snapshots" / "a.zip"
    assert (server.root / "snapshots" / "a.zip").is_file()
    assert not list(archive.parent.glob("*.tmp"))
    assert unpacked == 2
    assert recall(tool) == before


def test_own_snapshots_with_harmless_root_files_are_accepted_in_both_modes(tmp_path: Path, remote):
    server, _, _, remote_tool = remote
    local = MemoryTool(Embedder(), Reranker(), memory_root=tmp_path / "local")
    for tool, root in ((local, tmp_path / "local"), (remote_tool, server.root)):
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
        (root / "notes.txt").write_text("harmless", encoding="utf-8")
        before = recall(tool)

        archive = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="a"))
        tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
        tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=archive.archive))

        assert recall(tool) == before
        assert (root / "notes.txt").read_text(encoding="utf-8") == "harmless"
