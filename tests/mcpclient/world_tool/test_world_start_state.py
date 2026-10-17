"""起点持久绑定与 WRAM 读取经内存 MCP 传输保持字节不变。"""

from pathlib import Path
from typing import Any

import pytest

from pokemon_agent.brain.interface import Task
from pokemon_agent.mcpclient.world_tool import WorldMcpTool
from pokemon_agent.schemas.harness import FromHarnessToGameToolResetReq


def test_reset_keeps_start_state_until_cleared(
    tool: WorldMcpTool, client: Any, world: Any, tmp_path: Path
) -> None:
    """未绑定不加参数；绑定后每次都带；清除后恢复原请求。"""
    import base64

    request = FromHarnessToGameToolResetReq(
        task=Task(task_id="t1", goal="g", success_criteria="c", max_steps=10)
    )
    path = tmp_path / "start.state"
    data = b"\x00start\xff"
    path.write_bytes(data)

    tool.reset(request)
    original = dict(client.calls[-1][1])
    assert "state_base64" not in original
    assert "start_state" not in world.calls[-1][1]
    tool.use_start_state(path)
    path.write_bytes(b"changed after binding")
    for _ in range(2):
        tool.reset(request)
        assert base64.b64decode(client.calls[-1][1]["state_base64"]) == data
        assert world.calls[-1][1]["start_state"] == data
    tool.use_start_state(None)
    tool.reset(request)

    assert client.calls[-1][1] == original
    assert "start_state" not in world.calls[-1][1]


def test_use_start_state_rejects_empty_file(tool: WorldMcpTool, tmp_path: Path) -> None:
    path = tmp_path / "empty.state"
    path.write_bytes(b"")

    with pytest.raises(AssertionError, match="empty"):
        tool.use_start_state(path)


def test_read_wram_round_trips_bytes(tool: WorldMcpTool, world: Any, client: Any) -> None:
    data = tool.read_wram()

    assert data == world.read_wram() == bytes(range(256)) * 32
    assert client.calls == [("read_wram", {})]
