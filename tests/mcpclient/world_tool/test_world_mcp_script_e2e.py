"""e2e：脚本动作经 `WorldMcpTool.execute` → server 脚本 tool（in-memory transport 直连）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from _doubles.world_console import StubConsole

from pokemon_agent.brain.interface import Action
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene


def _obs(scene: TaskScene) -> TaskObservation:
    return TaskObservation(
        facts={"overlay": "none"}, step=0, scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


# ---- 8. e2e：脚本动作经 WorldMcpTool.execute → server 脚本 tool ----


class _InlineClient:
    """in-memory 版 `McpClient.call_tool_sync`：直连 server 实例，不起端口。"""

    def __init__(self, server: Any) -> None:
        self._server = server

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp.shared.memory import create_connected_server_and_client_session

        async def run() -> dict[str, Any]:
            async with create_connected_server_and_client_session(
                self._server.mcp._mcp_server
            ) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                assert not result.isError
                return dict(json.loads(result.content[0].text))

        return asyncio.run(run())


class _NoWorld:
    """脚本 tool 不经原子层——给个可辨识的占位即可。"""

    def get_action_space(self) -> None:
        raise AssertionError("脚本通道不应触碰原子层")


class _DialogConsole(StubConsole):
    """对话替身：每次按键换一屏，空屏即对话结束。"""

    def __init__(self, frames: list[str]) -> None:
        super().__init__()
        self._frames = frames
        self._i = 0

    def press(self, key: str) -> None:  # noqa: ARG002
        self._i = min(self._i + 1, len(self._frames) - 1)

    def read(self) -> Any:  # noqa: ANN401
        from pokemon_agent.world import ScreenText

        return ScreenText(dialog_text=self._frames[self._i])

    def scene(self) -> str:
        return "dialog" if self._frames[self._i] else "walk"


def test_world_mcp_tool_executes_script_over_mcp() -> None:
    from pokemon_agent.brain.interface import ScriptCall
    from pokemon_agent.mcp_servers import world_server
    from pokemon_agent.mcpclient.world_tool import WorldMcpTool
    from pokemon_agent.schemas.harness import FromHarnessToGameToolExecuteReq

    console = StubConsole()
    world_server.start(_NoWorld(), rom="fake.rom")
    world_server._lease_owner = None
    world_server.set_console_factory(lambda: console)

    tool = WorldMcpTool(_InlineClient(world_server), client_id="t")
    resp = tool.execute(
        FromHarnessToGameToolExecuteReq(
            action=Action(script=ScriptCall(name="face_direction", args={"direction": "west"})),
            observation=_obs(TaskScene.WALK),
        )
    )
    assert resp.report is not None and resp.report["ok"] is True
    assert resp.report["code"] == "ok"
    assert console.facing() == "west"


def test_world_mcp_tool_keeps_per_line_dialog_in_the_rebuilt_report() -> None:
    """客户端重建报告后仍带 `dialog`，且是逐行列表（D3 透传 / D9 覆盖）。"""
    from pokemon_agent.brain.interface import ScriptCall
    from pokemon_agent.mcp_servers import world_server
    from pokemon_agent.mcpclient.world_tool import WorldMcpTool
    from pokemon_agent.schemas.harness import FromHarnessToGameToolExecuteReq

    console = _DialogConsole(["第一行\n第二行", "第三行", ""])
    world_server.start(_NoWorld(), rom="fake.rom")
    world_server._lease_owner = None
    world_server.set_console_factory(lambda: console)

    tool = WorldMcpTool(_InlineClient(world_server), client_id="t")
    resp = tool.execute(
        FromHarnessToGameToolExecuteReq(
            action=Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
            observation=_obs(TaskScene.DIALOG),
        )
    )
    assert resp.report is not None
    assert resp.report["dialog"] == ["第一行", "第二行", "第三行"]
