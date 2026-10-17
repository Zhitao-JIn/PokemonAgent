"""world 仅经 MCP 连接，缺地址在装配期拒绝。"""

import pytest

from pokemon_agent.mcpclient.client import McpTransportError
from pokemon_agent.mcpclient.world_tool import WorldMcpTool


def test_world_build_requires_a_server_url() -> None:
    """空地址在启动客户端前报出部署变量名。"""
    with pytest.raises(ValueError, match="MCP_WORLD_SERVER_URL"):
        WorldMcpTool.build(world_server_url="")


def test_build_real_without_world_url_fails_at_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 world 地址在任何健康检查或 memory 装配前失败，不访问网络。"""
    import pokemon_agent.build as assembly

    monkeypatch.delenv("MCP_WORLD_SERVER_URL", raising=False)
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    calls: list[str] = []

    def unexpected_probe(*args: object) -> dict[str, object]:
        calls.append("health")
        raise AssertionError("缺 world 地址时不应探活")

    def unexpected_memory(**kwargs: object) -> object:
        calls.append("memory")
        raise AssertionError("缺 world 地址时不应装配 memory")

    monkeypatch.setattr(assembly, "assert_mcp_server_ready", unexpected_probe)
    monkeypatch.setattr(assembly.MemoryTool, "build", unexpected_memory)

    with pytest.raises(McpTransportError, match="MCP_WORLD_SERVER_URL"):
        assembly.build_real(trace_backend="local")

    assert calls == []
