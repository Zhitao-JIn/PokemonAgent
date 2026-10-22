"""模拟器入口的前置检查：文件存在性、参数校验、before-reset 与动作链整校。"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from pokemon_agent.world import OVERLAY_ACTIONS
from pokemon_agent.world.action_space import ALL_BUTTONS

module = importlib.import_module("pokemon_agent.world.pyboy_world")


class _PyBoy:
    """只记录按键、tick 与读档；tick 的返回值可切换，用来模拟窗口关闭。"""

    def __init__(self) -> None:
        self.buttons: list[tuple[str, int]] = []
        self.ticks: list[int] = []
        self.loaded: list[bytes] = []
        self.memory = bytes(0x10000)
        self.tick_result = True

    def set_emulation_speed(self, speed: int) -> None:
        """构造函数会调；世界速度与这一层的前置检查无关，只收下。"""

    def button(self, name: str, delay: int) -> None:
        self.buttons.append((name, delay))

    def tick(self, frames: int) -> bool:
        self.ticks.append(frames)
        return self.tick_result

    def load_state(self, stream: BinaryIO) -> None:
        self.loaded.append(stream.read())


def _world_with_fake_pyboy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _PyBoy]:
    """经公开构造函数装配：模块引用的 PyBoy 换成手写假件，ROM 是空的占位文件。"""
    fake = _PyBoy()
    monkeypatch.setattr(module, "PyBoy", lambda *args, **kwargs: fake)
    rom = tmp_path / "x.gb"
    rom.write_bytes(b"")
    return module.PyBoyWorld(str(rom), state_path=None), fake


def _reset_world(world: Any, fake: _PyBoy) -> None:
    """经公开 reset 准备，然后清空假件记录。"""
    world.reset(task_id="t", goal="g", success_criteria="c", max_steps=5, start_state=b"\x00")
    fake.buttons.clear()
    fake.ticks.clear()
    fake.loaded.clear()


def test_missing_start_file_fails_before_simulator_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(module, "PyBoy", lambda *args, **kwargs: calls.append("PyBoy"))

    with pytest.raises(FileNotFoundError, match="找不到存档"):
        module.PyBoyWorld(str(tmp_path / "missing.rom"), state_path=str(tmp_path / "gone.state"))

    assert calls == []


def test_missing_rom_fails_before_simulator_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(module, "PyBoy", lambda *args, **kwargs: calls.append("PyBoy"))

    with pytest.raises(FileNotFoundError, match="找不到 ROM"):
        module.PyBoyWorld(str(tmp_path / "missing.rom"), state_path=None)

    assert calls == []


@pytest.mark.parametrize("max_steps", [0, -1])
def test_reset_rejects_nonpositive_step_limits_before_loading(
    max_steps: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="max_steps"):
        world.reset(
            task_id="t",
            goal="g",
            success_criteria="c",
            max_steps=max_steps,
            start_state=b"\x00",
        )

    assert fake.loaded == []
    assert fake.ticks == []
    assert fake.buttons == []


@pytest.mark.parametrize("entry", ["step", "perceive_task", "get_action_space"])
def test_world_entries_require_reset_before_reading_or_acting(
    entry: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match=f"{entry}\\(\\) before reset"):
        if entry == "step":
            world.step([("a", 1)])
        else:
            getattr(world, entry)()

    assert fake.loaded == []
    assert fake.ticks == []
    assert fake.buttons == []


def test_step_rejects_a_closed_world_before_acting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)
    _reset_world(world, fake)
    fake.tick_result = False
    world.evolve(1)
    fake.buttons.clear()
    fake.ticks.clear()

    with pytest.raises(AssertionError, match="window was closed"):
        world.step([("a", 1)])

    assert fake.buttons == []
    assert fake.ticks == []


def test_step_validates_every_segment_before_any_button(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)
    _reset_world(world, fake)

    with pytest.raises(AssertionError, match="unknown action"):
        world.step([("a", 1), ("nope", 1)])

    assert fake.buttons == []
    assert fake.ticks == []


def test_evolve_rejects_negative_frames_before_ticking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="negative frames"):
        world.evolve(-1)

    assert fake.ticks == []


def test_load_state_rejects_empty_bytes_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, fake = _world_with_fake_pyboy(tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="empty bytes"):
        world.load_state(b"")

    assert fake.loaded == []
    assert fake.ticks == []


def test_overlay_buttons_belong_to_the_world_namespace() -> None:
    assert {button for buttons in OVERLAY_ACTIONS.values() for button in buttons} <= set(
        ALL_BUTTONS
    )
