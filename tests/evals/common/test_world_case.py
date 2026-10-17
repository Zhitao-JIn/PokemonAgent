"""评测侧世界装配改走 MCP：缺地址、起点绑定、开跑前按键与租约归还。"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.common import world_case
from pokemon_agent.mcpclient import McpTransportError


class _FakeWorld:
    """只记下 `start_world` / `stop_world` 对门面做了什么。"""

    built: list[_FakeWorld] = []

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    @classmethod
    def build(cls, *, world_server_url: str, client_id: str | None = None) -> _FakeWorld:
        instance = cls()
        cls.built.append(instance)
        instance.calls.append(("build", world_server_url, client_id))
        return instance

    def use_start_state(self, path: Path) -> None:
        self.calls.append(("use_start_state", path.read_bytes()))

    def reset(self, req: object) -> None:
        self.calls.append(("reset", req))

    def press(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        self.calls.append(("press", segments, settle))

    def release_lease(self) -> None:
        self.calls.append(("release_lease",))


def test_missing_world_url_raises_mcp_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 MCP_WORLD_SERVER_URL → McpTransportError（文案含变量名）。"""
    monkeypatch.setattr(world_case, "load_env_file", lambda: None)
    monkeypatch.setenv("MCP_WORLD_SERVER_URL", "")

    with pytest.raises(McpTransportError, match="MCP_WORLD_SERVER_URL"):
        world_case.world_url()


def test_start_world_binds_start_state_resets_and_presses_pre_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """起点字节先绑定、reset 用测评 task、pre 的键按序各一次 step。"""
    state = tmp_path / "start.state"
    data = b"\x00start\xff"
    state.write_bytes(data)
    monkeypatch.delenv("MCP_WORLD_CLIENT_ID", raising=False)
    monkeypatch.setattr(world_case, "world_url", lambda: "http://fake")
    monkeypatch.setattr(world_case, "WorldMcpTool", _FakeWorld)
    _FakeWorld.built = []

    world_case.start_world(state, ("up", "down"), case_id="c1")

    fake = _FakeWorld.built[0]
    assert fake.calls[0] == ("build", "http://fake", None)
    assert fake.calls[1] == ("use_start_state", data)
    reset_call = fake.calls[2]
    assert reset_call[0] == "reset"
    assert reset_call[1].task.task_id == "c1"
    assert reset_call[1].task.goal == "world 用例测评"
    assert fake.calls[3:] == [
        ("press", [("up", 1)], True),
        ("press", [("down", 1)], True),
    ]


def test_stop_world_releases_lease() -> None:
    """stop_world 归还租约，不再碰模拟器私有属性。"""
    fake = _FakeWorld()

    world_case.stop_world(fake)

    assert fake.calls == [("release_lease",)]
