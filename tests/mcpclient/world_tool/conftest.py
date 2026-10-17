"""WorldMcpTool 测试共用假世界与内存传输，不占端口、不创建模拟器。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pokemon_agent.mcp_servers import world_server
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


class _FakeWorld:
    """最小 `WorldPort`：只记下被调用了什么。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._pos = (12, 13, 8)

    def _observation(self) -> TaskObservation:
        return TaskObservation(
            step=0,
            status="你在野外。",
            scene=TaskScene.WALK,
            place=PlaceInWorld(map_id=self._pos[0], x=self._pos[1], y=self._pos[2]),
        )

    def reset(self, **kwargs: Any) -> None:
        self.calls.append(("reset", kwargs))

    def all_actions(self) -> list[str]:
        return list(ALL_BUTTONS)

    def get_action_space(self) -> Any:
        from pokemon_agent.world.action_space import compute_action_space

        return compute_action_space(self._observation(), list(ALL_BUTTONS))

    def perceive_task(self) -> Any:
        return type(
            "TaskPerceived",
            (),
            {"observation": self._observation(), "frame_png": "png", "ram": None},
        )()

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        self.calls.append(("step", (segments, settle)))
        self._pos = (self._pos[0], self._pos[1] + 1, self._pos[2])

    def save_state(self) -> bytes:
        return b"STATE"

    def read_wram(self) -> bytes:
        return bytes(range(256)) * 32

    def load_state(self, data: bytes) -> None:
        self.calls.append(("load_state", data))


class _InMemoryClient:
    """把 in-memory MCP session 包成 `WorldMcpTool` 要的同步 client 形状。"""

    def __init__(self, server: Any) -> None:
        self._server = server
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        import json

        from mcp.shared.memory import create_connected_server_and_client_session

        async def call() -> dict[str, Any]:
            async with create_connected_server_and_client_session(self._server) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return json.loads(result.content[0].text)

        return asyncio.run(call())


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _FakeWorld:
    """隔离服务端世界与租约，退出时恢复原模块状态。"""
    instance = _FakeWorld()
    monkeypatch.setattr(world_server, "_world", instance)
    monkeypatch.setattr(world_server, "_rom", "fake.rom")
    monkeypatch.setattr(world_server, "_lease_owner", None)
    monkeypatch.setattr(world_server, "_console_factory", None)
    return instance


@pytest.fixture
def client(world: _FakeWorld) -> _InMemoryClient:
    """使用真 MCP session，并记录门面发出的每次调用。"""
    return _InMemoryClient(world_server.mcp._mcp_server)


@pytest.fixture
def tool(client: _InMemoryClient) -> WorldMcpTool:
    """注入内存传输客户端，保留原租约身份。"""
    return WorldMcpTool(client, client_id="test-runner")  # type: ignore[arg-type]
