"""脚本 tool 注册层单测：world_server 的脚本 API 信封与转发。

**对得上谁**：脚本函数本体已在 test_scripts_* 里逐条验过；本文件只验
**server 壳**——tool 暴露、参数转发、租约、信封 code/events 装配
（`set_console_factory` 注入替身，不起真模拟器）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest  # noqa: E402
from _doubles.world_console import StubConsole

from pokemon_agent.mcp_servers import world_server
from pokemon_agent.mcp_servers.common import _CODES


@pytest.fixture()
def console() -> StubConsole:
    c = StubConsole()
    world_server.start(_FakeWorld(), rom="fake.rom")
    world_server._lease_owner = None
    world_server.set_console_factory(lambda: c)
    return c


class _FakeWorld:
    """占位 world：脚本 tool 不经 `_w()`（console 工厂注入），给个可辨识对象即可。"""

    def get_action_space(self) -> None:
        raise AssertionError("脚本 tool 不应触碰原子层")


def _call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mcp.shared.memory import create_connected_server_and_client_session

    async def run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(
            world_server.mcp._mcp_server
        ) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            return json.loads(result.content[0].text)

    return asyncio.run(run())


def test_script_tool_registered(console: StubConsole) -> None:
    """注册表核对：14 个脚本名都在 tools/list（一脚本一 API）。"""
    from mcp.shared.memory import create_connected_server_and_client_session

    async def run() -> list[str]:
        async with create_connected_server_and_client_session(
            world_server.mcp._mcp_server
        ) as session:
            await session.initialize()
            res = await session.list_tools()
            return [t.name for t in res.tools]

    names = asyncio.run(run())
    for name in (
        "face_direction",
        "walk_to_adjacent",
        "walk_to",
        "circle_walk",
        "bounce_in_tall_grass",
        "talk_to_adjacent_npc",
        "buy_item",
        "sell_item",
        "interact_facing",
        "advance_dialog",
        "wait_until_scene",
        "exit_map",
        "heal_at_center",
        "open_menu_to",
    ):
        assert name in names, f"{name} 未注册"


def test_walk_to_adjacent_forwarding(console: StubConsole) -> None:
    """参数转发 + 信封装配：data.ok / final_pos 都在。"""
    console._walkable = {(16, 8)}
    res = _call("walk_to_adjacent", {"direction": "east", "client_id": "t"})
    assert res["ok"] is True and res["code"] == "ok"
    assert res["data"]["final_pos"]["x"] == 16
    assert res["events"] == []


def test_walk_to_adjacent_blocked_envelope(console: StubConsole) -> None:
    """blocked 也是合法结局码：信封 ok=False 但不是 transport 错误。"""
    res = _call("walk_to_adjacent", {"direction": "east", "client_id": "t"})
    assert res["ok"] is False and res["code"] == "blocked"
    assert res["code"] in _CODES


def test_buy_item_end_to_end(console: StubConsole) -> None:
    """buy_item 经 server 全链路：扣款入库都在替身上发生。"""
    res = _call("buy_item", {"item": "POKé BALL", "count": 2, "client_id": "t"})
    assert res["ok"] is True and res["code"] == "ok"
    assert res["data"]["spent"] == 400
    assert res["data"]["remaining_money"] == 2600
    assert res["data"]["stock"] == 2


def test_script_tool_takes_lease(console: StubConsole) -> None:
    """租约：第一个 client 占住后，第二个 client 的脚本调用被拒。"""
    console._walkable = {(16, 8)}
    first = _call("walk_to_adjacent", {"direction": "east", "client_id": "a"})
    assert first["ok"] is True
    second = _call("walk_to_adjacent", {"direction": "east", "client_id": "b"})
    assert second["ok"] is False and second["code"] == "rejected"


def test_release_lease_allows_next_client(console: StubConsole) -> None:
    console._walkable = {(14, 8), (15, 8), (16, 8), (17, 8)}
    _call("walk_to_adjacent", {"direction": "east", "client_id": "a"})
    _call("release_lease", {"client_id": "a"})
    again = _call("walk_to_adjacent", {"direction": "west", "client_id": "b"})
    assert again["ok"] is True
