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


def test_world_mcp_tool_rebuilt_report_has_observations_without_legacy_fields() -> None:
    """客户端重建脚本报告时只保留逐键观察，不再带事件与独立对话字段。"""
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
    assert "events" not in resp.report and "dialog" not in resp.report
    assert [item["dialog_text"] for item in resp.report["observations"]] == ["第三行", ""]


def test_script_observations_survive_the_server_client_and_trace_round_trip() -> None:
    """替身逐键观察经真实 MCP 信封、客户端重建、trace 落盘再 parse，字段完整。"""
    from tempfile import TemporaryDirectory

    from pokemon_agent.brain.interface import ScriptCall
    from pokemon_agent.direct.trace import TraceTool, parse
    from pokemon_agent.mcp_servers import world_server
    from pokemon_agent.mcpclient.world_tool import WorldMcpTool
    from pokemon_agent.schemas.harness import (
        FromHarnessToGameToolExecuteReq,
        FromHarnessToTraceToolAppendReq,
        TraceKind,
    )
    from pokemon_agent.world import StepObservation

    console = _DialogConsole(["第一行", "第二行", ""])
    world_server.start(_NoWorld(), rom="fake.rom")
    world_server._lease_owner = None
    world_server.set_console_factory(lambda: console)
    action = Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10}))
    tool = WorldMcpTool(_InlineClient(world_server), client_id="t")

    response = tool.execute(
        FromHarnessToGameToolExecuteReq(action=action, observation=_obs(TaskScene.DIALOG))
    )

    assert response.report is not None
    snapshots = response.report["observations"]
    assert len(snapshots) == response.report["presses"] == 2
    assert [snapshot["dialog_text"] for snapshot in snapshots] == ["第二行", ""]
    assert all(snapshot["ram"] is not None and snapshot["settled"] for snapshot in snapshots)
    with TemporaryDirectory() as directory:
        trace = TraceTool.build(run_id="r", trace_root=directory)
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACT_CALL,
                meta={"source": "act", "episode_id": "ep", "task_id": "t", "step": 1},
                action=action,
                report=response.report,
            )
        )
        (event,) = trace.read_events(meta={"run_id": "r"})
        parsed = parse(event)
    assert parsed.content.observations == [StepObservation.model_validate(s) for s in snapshots]
    assert "dialog" not in response.report and "events" not in response.report
    assert "dialog" not in parsed.content.model_fields_set
