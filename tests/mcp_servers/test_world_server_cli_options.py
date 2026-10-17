"""world server 的窗口与速度选项在服务端装配时生效。"""

import sys
from types import SimpleNamespace

import pytest

import pokemon_agent.world as world_module
from pokemon_agent.mcp_servers.common import MCP_PATH
from pokemon_agent.mcp_servers.world_server_cli import main


@pytest.mark.parametrize(
    "flags,watch,speed", [([], False, 0), (["--watch", "--speed", "1"], True, 1)]
)
def test_world_server_cli_passes_watch_and_speed_to_the_world(
    monkeypatch: pytest.MonkeyPatch, flags: list[str], watch: bool, speed: int
) -> None:
    """以假世界记录默认与显式旋钮；服务运行入口替换为无副作用替身。"""
    constructors: list[dict[str, object]] = []
    starts: list[tuple[object, str]] = []
    instance = object()

    def fake_world(
        rom: str, *, state_path: str | None, watch: bool = False, speed: int = 0
    ) -> object:
        constructors.append(dict(rom=rom, state_path=state_path, watch=watch, speed=speed))
        return instance

    monkeypatch.setitem(world_module.__dict__, "PyBoyWorld", fake_world)
    monkeypatch.setattr(sys, "argv", ["world-server", "--rom", "fake.rom", *flags])
    server = SimpleNamespace(
        settings=SimpleNamespace(streamable_http_path=MCP_PATH), run=lambda **kwargs: None
    )

    main(server, lambda world, rom: starts.append((world, rom)), "test-world")

    assert constructors == [dict(rom="fake.rom", state_path=None, watch=watch, speed=speed)]
    assert starts == [(instance, "fake.rom")]
