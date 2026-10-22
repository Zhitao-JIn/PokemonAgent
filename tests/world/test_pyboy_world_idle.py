"""可视窗口空闲期间泵送 PyBoy，但不推进游戏帧。"""

from typing import Any

from pyboy.utils import WindowEvent

from pokemon_agent.world.pyboy_world import PyBoyWorld


class _PausedPyBoy:
    def __init__(self) -> None:
        self.paused = False
        self.frame_count = 0
        self.window_refreshes = 0
        self.events: list[int] = []

    def send_input(self, event: int) -> None:
        self.events.append(event)

    def tick(self, _count: int) -> bool:
        for event in self.events:
            if event == WindowEvent.PAUSE:
                self.paused = True
            elif event == WindowEvent.UNPAUSE:
                self.paused = False
            elif event == WindowEvent._INTERNAL_RENDERER_FLUSH:
                self.window_refreshes += 1
        self.events.clear()
        if not self.paused:
            self.frame_count += 1
        return True


def test_idle_window_ticks_keep_game_paused_and_actions_resume_exact_frames() -> None:
    world: Any = object.__new__(PyBoyWorld)
    pyboy = _PausedPyBoy()
    world._pyboy = pyboy
    world._watch = True
    world._closed = False
    world._idle_paused = False
    world._pump_window_events = lambda: None

    world._pump_idle_window()
    world._pump_idle_window()

    assert pyboy.paused is True
    assert pyboy.frame_count == 0
    assert pyboy.window_refreshes == 2

    world._tick(2)

    assert pyboy.paused is False
    assert pyboy.frame_count == 2

    world._pump_idle_window()

    assert pyboy.paused is True
    assert pyboy.frame_count == 2
    assert pyboy.window_refreshes == 3
