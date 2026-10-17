"""不构造模拟器，直接验证起点优先级与 WRAM 只读契约。"""

import importlib
from pathlib import Path
from typing import Any, BinaryIO

import pytest


class _PyBoy:
    """只提供读档与可切片内存；不存在推进接口。"""

    def __init__(self) -> None:
        self.loaded: list[bytes] = []
        self.memory = bytes(range(256)) * 256

    def load_state(self, stream: BinaryIO) -> None:
        self.loaded.append(stream.read())


@pytest.fixture
def world() -> Any:
    """绕过构造函数，用假内存和帧计数器注入唯一实现。"""
    module = importlib.import_module("pokemon_agent.world.pyboy_world")
    instance = object.__new__(module.PyBoyWorld)
    instance._pyboy = _PyBoy()
    instance._state_path = None
    instance.ticks = []
    instance._tick = instance.ticks.append
    return instance


def _reset(world: Any, **kwargs: Any) -> None:
    world.reset(task_id="t1", goal="g", success_criteria="c", max_steps=10, **kwargs)


def test_start_state_takes_priority_over_missing_state_path(world: Any, tmp_path: Path) -> None:
    world._state_path = str(tmp_path / "missing.state")

    _reset(world, start_state=b"\x00sample\xff")

    assert world._pyboy.loaded == [b"\x00sample\xff"]
    assert world.ticks == [1]
    assert world._task.task_id == "t1"
    assert world._closed is False


def test_reset_without_start_state_reads_configured_file(world: Any, tmp_path: Path) -> None:
    path = tmp_path / "configured.state"
    path.write_bytes(b"configured")
    world._state_path = str(path)

    _reset(world)

    assert world._pyboy.loaded == [b"configured"]
    assert world.ticks == [1]


def test_reset_without_any_state_boots(world: Any) -> None:
    module = importlib.import_module("pokemon_agent.world.pyboy_world")

    _reset(world)

    assert world._pyboy.loaded == []
    assert world.ticks == [module.BOOT_FRAMES]


def test_reset_refuses_empty_start_state(world: Any) -> None:
    with pytest.raises(AssertionError, match="empty"):
        _reset(world, start_state=b"")

    assert world._pyboy.loaded == []
    assert world.ticks == []


def test_read_wram_returns_only_the_wram_slice_without_ticking(world: Any) -> None:
    data = world.read_wram()

    assert data == world._pyboy.memory[0xC000:0xE000]
    assert len(data) == 8192
    assert world.ticks == []


def test_read_wram_rejects_wrong_length(world: Any) -> None:
    world._pyboy.memory = b""

    with pytest.raises(AssertionError, match="8192"):
        world.read_wram()

    assert world.ticks == []
