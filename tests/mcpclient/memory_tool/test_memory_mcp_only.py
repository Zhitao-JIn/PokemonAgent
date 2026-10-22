"""memory 只经 MCP 装配，四个 Port 信封通过真实服务端往返。"""

import json
from pathlib import Path

import pytest
from _doubles.memory_server import act, memory_server_context

from pokemon_agent.mcpclient.client import McpTransportError
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
)


def test_build_requires_a_server_url() -> None:
    """空地址在启动客户端前报出部署变量名。"""
    with pytest.raises(ValueError, match="services.memory_server_url"):
        MemoryTool.build(memory_server_url="")


def test_build_real_without_memory_url_fails_at_assembly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """清空部署环境，装配期拒绝缺地址；不连接网络、不创建模拟器或模型。"""
    import pokemon_agent.build as assembly

    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "services": {"world_server_url": "http://example", "memory_server_url": None},
                "paths": {"runs_root": str(tmp_path)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: object())

    def world_probe(url: str, service: str) -> dict[str, object]:
        assert service == "world", "memory 缺地址时不能探活"
        return {}

    monkeypatch.setattr(assembly, "assert_mcp_server_ready", world_probe)

    with pytest.raises(McpTransportError, match="services.memory_server_url"):
        assembly.build_real(overlay)


def test_memory_tool_round_trips_all_four_calls_through_a_real_server(tmp_path: Path) -> None:
    """记忆、快照、恢复、召回均走 MCP，客户端路径不暴露服务端路径。"""
    with memory_server_context(tmp_path / "server", tmp_path / "client") as (capability, tool):
        stored = tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
        snapshot = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="roundtrip"))
        capability.memorize([act(9)])
        restored = tool.restore_memory(
            FromHarnessToMemoryToolRestoreMemoryReq(archive=snapshot.archive)
        )
        recalled = tool.recall(
            FromHarnessToMemoryToolRecallReq(query="", conditions={"episode_id": "episode"})
        )

        assert len(stored.stored) == len(recalled.items) == 1
        assert stored.stored[0].kind == recalled.items[0].kind == "act"
        assert stored.stored[0].uuid == recalled.items[0].uuid
        assert recalled.items[0].payload == act(1)["payload"]
        assert restored.unpacked == 2
        assert Path(snapshot.archive) == tmp_path / "client" / "snapshots" / "roundtrip.zip"
        assert Path(snapshot.archive).is_file()
