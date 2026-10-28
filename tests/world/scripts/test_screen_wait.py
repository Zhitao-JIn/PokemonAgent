"""合成轮询序列验证统一画面稳定等待。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _doubles.world_console import FakeMemory

from pokemon_agent.world import PlaceInWorld, ScreenText, TaskScene
from pokemon_agent.world.scene import W_IS_IN_BATTLE
from pokemon_agent.world.scripts import console_adapter as adapter_module
from pokemon_agent.world.scripts.control_flow import Abort
from pokemon_agent.world.scripts.navigation import _heal_wait
from pokemon_agent.world.scripts.policies import StableWait
from pokemon_agent.world.scripts.screen_wait import wait_settled


class PollingConsole:
    """按 tick 顺序返回合成屏幕与战斗分类的 WorldConsole。"""

    def __init__(self, frames: list[tuple[str, bool]]) -> None:
        self.frames = frames
        self.index = 0
        self.waited = 0
        self.memory = FakeMemory()
        self.rom = b""

    def press(self, key: str) -> None:  # noqa: ARG002
        pass

    def tick(self, frames: int) -> None:
        self.waited += frames
        self.index = min(self.index + 1, len(self.frames) - 1)
        self.memory = FakeMemory(**{str(W_IS_IN_BATTLE): int(self.frames[self.index][1])})

    def read(self) -> ScreenText:
        screen, _battle = self.frames[self.index]
        return ScreenText(screen=screen)

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=12, x=13, y=8)


def steady_frames(count: int, screen: str = "same") -> list[tuple[str, bool]]:
    return [(screen, False)] * count


def test_wait_requires_first_sample_and_exactly_stable_polls_equal_comparisons() -> None:
    console = PollingConsole(steady_frames(4))

    result = wait_settled(console, StableWait(stable_polls=3, timeout_frames=12))

    assert result.settled is True
    assert result.waited_frames == 12


def test_one_fewer_equal_comparison_does_not_settle() -> None:
    console = PollingConsole(steady_frames(3))

    result = wait_settled(console, StableWait(stable_polls=3, timeout_frames=8))

    assert result.settled is False
    assert result.waited_frames == 8


def test_changed_screen_restarts_equal_comparison_count() -> None:
    console = PollingConsole([("a", False), ("a", False), ("b", False), ("b", False), ("b", False)])

    result = wait_settled(console, StableWait(stable_polls=2, timeout_frames=20))

    assert result.settled is True
    assert result.waited_frames == 16


def test_changed_player_position_restarts_equal_comparison_count() -> None:
    class MovingConsole(PollingConsole):
        def pos(self) -> PlaceInWorld:
            x = 13 if self.index == 0 else 14
            return PlaceInWorld(map_id=12, x=x, y=8)

    console = MovingConsole(steady_frames(4))

    result = wait_settled(console, StableWait(stable_polls=2, timeout_frames=20))

    assert result.settled is True
    assert result.waited_frames == 12


@pytest.mark.parametrize("abort_on_timeout", [False, True])
def test_timeout_reports_unsettled_or_aborts_by_policy(abort_on_timeout: bool) -> None:
    console = PollingConsole([("a", False), ("b", False), ("a", False)])
    settings = StableWait(stable_polls=3, timeout_frames=8, abort_on_timeout=abort_on_timeout)

    if abort_on_timeout:
        with pytest.raises(Abort):
            wait_settled(console, settings)
    else:
        result = wait_settled(console, settings)
        assert result.settled is False and result.waited_frames == 8


def test_default_wait_uses_six_equal_polls_and_900_frame_budget() -> None:
    console = PollingConsole(steady_frames(7))

    result = wait_settled(console)

    assert StableWait().timeout_frames == 900
    assert result.settled is True and result.waited_frames == 24


def test_battle_wait_uses_1200_frame_budget_when_screen_never_settles() -> None:
    frames = [(str(index % 2), False) for index in range(301)]
    console = PollingConsole(frames)

    result = wait_settled(console, before_scene=TaskScene.BATTLE)

    assert result.settled is False and result.waited_frames == 1200


def test_battle_scene_is_sticky_after_scene_returns_to_walk() -> None:
    frames = [("same", False), ("same", True)] + steady_frames(45)[2:]
    console = PollingConsole(frames)

    result = wait_settled(console)

    assert result.settled is True and result.waited_frames == 180


def test_battle_scene_before_press_selects_battle_budget() -> None:
    console = PollingConsole(steady_frames(46))

    result = wait_settled(console, before_scene=TaskScene.BATTLE)

    assert result.settled is True and result.waited_frames == 180


def test_heal_wait_declares_360_quiet_frames_and_combines_with_battle_sticky() -> None:
    settings = _heal_wait()
    console = PollingConsole(steady_frames(91))

    result = wait_settled(console, settings)

    assert (settings.stable_polls, settings.timeout_frames) == (90, 1200)
    assert result.settled is True and result.waited_frames == 360


def test_heal_and_battle_settings_take_the_larger_threshold_and_budget() -> None:
    settings = _heal_wait()
    frames = [("same", False), ("same", True)] + steady_frames(91)[2:]
    console = PollingConsole(frames)

    result = wait_settled(console, settings)

    assert result.settled is True and result.waited_frames == 360


def test_adapter_decodes_only_once_for_read_and_scene_in_one_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def decode(memory: bytearray) -> ScreenText:  # noqa: ARG001
        nonlocal calls
        calls += 1
        return ScreenText()

    monkeypatch.setattr(adapter_module, "read_screen_text", decode)
    pyboy = SimpleNamespace(memory=bytearray(65536), button=lambda key, delay: None)
    world = SimpleNamespace(_pyboy=pyboy, _rom=b"", _tick=lambda frames: None)
    console = adapter_module.WorldConsoleAdapter(world)

    console.read()
    console.scene()
    assert calls == 1

    console.tick(4)
    console.read()
    assert calls == 2

    console.press("a")
    console.read()
    assert calls == 3
