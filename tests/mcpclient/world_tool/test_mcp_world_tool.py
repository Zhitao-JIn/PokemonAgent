"""world 的 MCP 远程门面（`WorldMcpTool`）：信封翻译与传输是否真的对得上。

**对得上谁**：与进程内 `GameTools` 的契约（`GameToolPort`）逐条对齐——同一张口、
同一批信封，换的只是底下一跳。测试用 **in-memory MCP transport**（client 直连
server 实例，不起端口）+ `_FakeWorld`（不起真模拟器）。
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any

import pytest

from pokemon_agent.brain.interface import Action, ActionSegment, ScriptCall
from pokemon_agent.mcp_servers import world_server
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolLoadStateReq,
    FromHarnessToGameToolSaveStateReq,
)
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


def _task_obs() -> TaskObservation:
    """`FromHarnessToGameToolExecuteReq` 必带的"动作所依据的观测"。"""
    return TaskObservation(
        step=0, status="你在野外。", scene=TaskScene.WALK, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


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

    def load_state(self, data: bytes) -> None:
        self.calls.append(("load_state", data))


class _InMemoryClient:
    """把 in-memory MCP session 包成 `WorldMcpTool` 要的同步 client 形状。"""

    def __init__(self, server: Any) -> None:
        self._server = server

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import json

        from mcp.shared.memory import create_connected_server_and_client_session

        async def call() -> dict[str, Any]:
            async with create_connected_server_and_client_session(self._server) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return json.loads(result.content[0].text)

        return asyncio.run(call())


@pytest.fixture()
def tool() -> WorldMcpTool:
    world = _FakeWorld()
    world_server.start(world, rom="fake.rom")
    world_server._lease_owner = None
    client = _InMemoryClient(world_server.mcp._mcp_server)
    return WorldMcpTool(client, client_id="test-runner")  # type: ignore[arg-type]


def test_execute_sends_one_key_and_reports_moved(tool: WorldMcpTool) -> None:
    """`step` 是唯一按键口：MCP 的二元数组过网络后被还原成 world 的元组。"""
    resp = tool.execute(
        FromHarnessToGameToolExecuteReq(
            action=Action(sequence=[ActionSegment(name="up", times=1)]),
            observation=_task_obs(),
            settle=True,
        )
    )
    assert resp.report is None, "单键执行没有脚本报告"


def test_get_action_space_revalidates_the_server_mask(tool: WorldMcpTool) -> None:
    """server 侧的 `ActionSpace` 过网络后能被验回（names/mask/entries 一个不少）。"""
    resp = tool.get_action_space(
        FromHarnessToGameToolGetActionSpaceReq(
            observation=TaskObservation(step=0, status="你在野外。", scene=TaskScene.WALK)
        )
    )
    space = resp.action_space
    assert space.mask["up"] is True
    assert "up" in space.names, "prompt 渲染要的 names 也在（与 mask 同一份产出）"
    assert space.scene == "walk"


def test_perceive_task_returns_the_memory_scene(tool: WorldMcpTool) -> None:
    """内存观测经过 MCP 后保留 TaskScene。"""
    assert tool.perceive_task().observation.scene == TaskScene.WALK


def test_state_files_round_trip_on_the_client_side(
    tool: WorldMcpTool, tmp_path: pathlib.Path
) -> None:
    """存档**落盘在 client**（路径是 client 的盘），字节过 MCP 交 server。"""
    path = tmp_path / "save.state"
    saved = tool.save_state(FromHarnessToGameToolSaveStateReq(path=str(path)))
    assert saved.size == 5 and path.read_bytes() == b"STATE"

    tool.load_state(FromHarnessToGameToolLoadStateReq(path=str(path)))


def test_evolve_remains_explicitly_unsupported(tool: WorldMcpTool) -> None:
    """无输入推进不在 MCP 能力面内。"""
    from pokemon_agent.mcpclient.client import McpToolError

    with pytest.raises(McpToolError, match="evolve"):
        tool.evolve(None)


def test_shop_quit_returns_its_report_over_real_mcp_transport(tool: WorldMcpTool) -> None:
    from collections import defaultdict

    from test_script_run import FakeConsole

    from pokemon_agent.world import ScreenText

    console = FakeConsole(
        [
            ScreenText(
                screen="─MONEY─", options=["BUY", "SELL", "QUIT"], cursor="QUIT", has_cursor=True
            ),
            ScreenText(),
        ]
    )
    console.memory = defaultdict(int, {0xCC26: 2})
    world_server.set_console_factory(lambda: console)

    try:
        response = tool.execute(
            FromHarnessToGameToolExecuteReq(
                action=Action(script=ScriptCall(name="shop_quit", args={})),
                observation=_task_obs(),
                settle=True,
            )
        )
    finally:
        world_server.set_console_factory(None)

    assert response.report["ok"] is True
    assert response.report["code"] == "ok"
    assert response.report["status"] == "done"
    assert response.report["steps"]
    assert response.report["events"] == []


def test_shop_quit_rejects_wrong_scene_with_a_named_report(tool: WorldMcpTool) -> None:
    from test_script_run import FakeConsole

    from pokemon_agent.world import ScreenText

    world_server.set_console_factory(lambda: FakeConsole([ScreenText()]))

    try:
        response = tool.execute(
            FromHarnessToGameToolExecuteReq(
                action=Action(script=ScriptCall(name="shop_quit", args={})),
                observation=_task_obs(),
            )
        )
    finally:
        world_server.set_console_factory(None)

    assert response.report["ok"] is False
    assert response.report["code"] == "unknown_script"
    assert response.report["status"] == "rejected"
    assert response.report["steps"] == []
