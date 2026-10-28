"""WorldPort 动作响应时间的最小契约。"""

from types import SimpleNamespace
from typing import Any


def test_step_only_presses_key_without_waiting_for_settlement() -> None:
    from pokemon_agent.world.pyboy_world import PRESS_FRAMES, PyBoyWorld

    world: Any = object.__new__(PyBoyWorld)
    ticks: list[int] = []
    presses: list[tuple[str, int]] = []
    world._pyboy = SimpleNamespace(button=lambda name, delay: presses.append((name, delay)))
    world._task = object()
    world._closed = False
    world._tick = ticks.append

    world.step([("a", 1)])

    assert presses == [("a", PRESS_FRAMES)]
    assert ticks == []
