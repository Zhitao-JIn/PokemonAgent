"""不构造模拟器，直接验证起点优先级与 WRAM 只读契约。"""

import ctypes
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO

import pytest


class _PyBoy:
    """只提供读档与可切片内存；不存在推进接口。"""

    def __init__(self) -> None:
        self.loaded: list[bytes] = []
        self.memory = bytes(range(256)) * 256
        self.events: list[int] = []

    def load_state(self, stream: BinaryIO) -> None:
        self.loaded.append(stream.read())

    def send_input(self, event: int) -> None:
        self.events.append(event)


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


@pytest.mark.parametrize("close_event", [False, True])
def test_watch_pumps_sdl_events_without_forwarding_keyboard_input(
    world: Any, monkeypatch: pytest.MonkeyPatch, close_event: bool
) -> None:
    world._watch = True
    received: list[int] = []
    queued: list[int] = []

    class _WindowEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint32),
            ("timestamp", ctypes.c_uint32),
            ("window_id", ctypes.c_uint32),
            ("event", ctypes.c_uint8),
        ]

    class _Event(ctypes.Union):
        _fields_ = [("type", ctypes.c_uint32), ("window", _WindowEvent)]

    event_type = 0x100 if close_event else 0x300
    window_event = 14 if close_event else 0

    def _poll(pointer: Any) -> int:
        if received:
            return 0
        event = ctypes.cast(pointer, ctypes.POINTER(_Event)).contents
        event.type = event_type
        event.window.event = window_event
        received.append(event_type)
        return 1

    def _send_input(event: int) -> None:
        queued.append(event)

    world._pyboy.send_input = _send_input

    sdl2 = SimpleNamespace(
        SDL_Event=_Event,
        SDL_PollEvent=_poll,
        SDL_QUIT=0x100,
        SDL_WINDOWEVENT=0x200,
        SDL_WINDOWEVENT_CLOSE=14,
    )
    monkeypatch.setitem(sys.modules, "sdl2", sdl2)

    world._pump_window_events()

    assert received == [event_type]
    assert bool(queued) is close_event
