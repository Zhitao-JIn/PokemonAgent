"""world server 的窗口与速度选项在服务端装配时生效。"""

import sys
from types import SimpleNamespace

import pytest

import pokemon_agent.world as world_module
from pokemon_agent.mcp_servers import world_server_cli
from pokemon_agent.mcp_servers.common import MCP_PATH


@pytest.mark.parametrize(
    "flags,watch,speed,state_file,preview",
    [
        ([], False, 0, None, False),
        (["--watch", "--speed", "1"], True, 1, None, False),
        (["--watch", "--state-file", "start.state"], True, 0, "start.state", True),
    ],
)
def test_world_server_cli_passes_watch_and_speed_to_the_world(
    monkeypatch: pytest.MonkeyPatch,
    flags: list[str],
    watch: bool,
    speed: int,
    state_file: str | None,
    preview: bool,
) -> None:
    """以假世界记录默认与显式旋钮；服务运行入口替换为无副作用替身。"""
    constructors: list[dict[str, object]] = []
    starts: list[tuple[object, str]] = []
    resets: list[dict[str, object]] = []
    watched: list[tuple[object, object]] = []
    runs: list[dict[str, object]] = []
    instance = SimpleNamespace(reset=lambda **kwargs: resets.append(kwargs))

    def fake_world(
        rom: str, *, state_path: str | None, watch: bool = False, speed: int = 0
    ) -> object:
        constructors.append(dict(rom=rom, state_path=state_path, watch=watch, speed=speed))
        return instance

    monkeypatch.setitem(world_module.__dict__, "PyBoyWorld", fake_world)
    monkeypatch.setattr(sys, "argv", ["world-server", "--rom", "fake.rom", *flags])
    server = SimpleNamespace(
        settings=SimpleNamespace(streamable_http_path=MCP_PATH),
        run=lambda **kwargs: runs.append(kwargs),
    )
    monkeypatch.setattr(
        world_server_cli,
        "_run_watching_server",
        lambda target, current_world: watched.append((target, current_world)),
    )

    world_server_cli.main(server, lambda world, rom: starts.append((world, rom)), "test-world")

    assert constructors == [dict(rom="fake.rom", state_path=state_file, watch=watch, speed=speed)]
    assert starts == [(instance, "fake.rom")]
    assert bool(resets) is preview
    assert watched == ([(server, instance)] if watch else [])
    assert runs == ([] if watch else [{"transport": "streamable-http"}])
    if preview:
        assert resets == [
            dict(
                task_id="startup-preview",
                goal="显示配置的初始存档。",
                success_criteria="初始存档画面已载入。",
                max_steps=1,
            )
        ]
