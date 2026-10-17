"""评测侧直连口：`press` / `call_script` 不做掩码断言，`client_id` 三级优先级。"""

from __future__ import annotations

import os
from typing import Any

import pytest

from pokemon_agent.mcpclient.client import McpToolError
from pokemon_agent.mcpclient.world_tool import WorldMcpTool


class _FakeClient:
    """只记下门面发出的调用，按需返回固定信封或抛异常。"""

    def __init__(
        self, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._result = result
        self._error = error

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if self._error is not None:
            raise self._error
        assert self._result is not None, "no canned result"
        return self._result


def test_press_sends_step_with_client_id_and_settle_without_mask_lookup(
    tool: WorldMcpTool, client: Any, world: Any
) -> None:
    """press 直接发 step、带 client_id 与 settle；不做掩码断言（无 get_action_space 调用）。"""
    tool.press([("up", 1)], settle=False)

    assert client.calls == [
        ("step", {"segments": [["up", 1]], "settle": False, "client_id": "test-runner"})
    ]
    assert world.calls[-1] == ("step", ([("up", 1)], False))


def test_press_sends_each_segment_with_its_times(tool: WorldMcpTool, client: Any) -> None:
    """多段按键原样展开成二元数组。"""
    tool.press([("up", 2), ("left", 1)])

    assert client.calls[-1] == (
        "step",
        {"segments": [["up", 2], ["left", 1]], "settle": True, "client_id": "test-runner"},
    )


def test_call_script_returns_full_envelope_without_raising_on_non_ok() -> None:
    """脚本失败码不抛异常，信封照回。"""
    envelope = {
        "ok": False,
        "code": "blocked",
        "data": {"ok": False, "code": "blocked", "calls": []},
        "events": [],
    }
    client = _FakeClient(result=envelope)
    tool = WorldMcpTool(client, client_id="eval")

    result = tool.call_script("walk_to_adjacent", {"direction": "north"})

    assert result is envelope
    assert client.calls == [("walk_to_adjacent", {"direction": "north", "client_id": "eval"})]


def test_call_script_propagates_server_side_error() -> None:
    """server 侧异常（McpToolError）向上传递。"""
    client = _FakeClient(error=McpToolError("server boom"))
    tool = WorldMcpTool(client, client_id="eval")

    with pytest.raises(McpToolError, match="server boom"):
        tool.call_script("shop_quit", {})


def test_client_id_priority_param_then_env_then_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """client_id 缺省优先级：构造参数 > MCP_WORLD_CLIENT_ID > harness-<pid>。"""
    monkeypatch.delenv("MCP_WORLD_CLIENT_ID", raising=False)
    monkeypatch.setenv("MCP_WORLD_CLIENT_ID", "from-env")
    assert WorldMcpTool(_FakeClient()).client_id == "from-env"
    assert WorldMcpTool(_FakeClient(), client_id="from-param").client_id == "from-param"

    monkeypatch.delenv("MCP_WORLD_CLIENT_ID")
    assert WorldMcpTool(_FakeClient()).client_id == f"harness-{os.getpid()}"
