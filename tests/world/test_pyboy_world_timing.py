"""WorldPort 动作响应时间的最小契约。"""

from types import SimpleNamespace
from typing import Any


def test_settle_false_step_executes_press_frames_without_waiting_for_stability() -> None:
    from pokemon_agent.world.pyboy_world import PRESS_FRAMES, PyBoyWorld

    world: Any = object.__new__(PyBoyWorld)
    ticks: list[int] = []
    presses: list[tuple[str, int]] = []
    world._pyboy = SimpleNamespace(button=lambda name, delay: presses.append((name, delay)))
    world._task = object()
    world._closed = False
    world._tick = ticks.append

    world.step([("a", 1)], settle=False)

    assert presses == [("a", PRESS_FRAMES)]
    assert ticks == [PRESS_FRAMES]


def test_each_consecutive_key_advances_press_frames_before_the_next_key() -> None:
    from pokemon_agent.world.pyboy_world import PRESS_FRAMES, PyBoyWorld

    world: Any = object.__new__(PyBoyWorld)
    events: list[tuple[str, str | int]] = []
    world._pyboy = SimpleNamespace(button=lambda name, delay: events.append(("button", name)))
    world._task = object()
    world._closed = False

    def tick(frames: int) -> None:
        events.append(("tick", frames))

    world._tick = tick

    world.step([("a", 1), ("b", 1)], settle=False)

    assert events == [
        ("button", "a"),
        ("tick", PRESS_FRAMES),
        ("button", "b"),
        ("tick", PRESS_FRAMES),
    ]
