"""逐键紧凑观察的契约：RAM、目标、稳定性与中断前的最后一键。"""

from __future__ import annotations

import pytest
from _doubles.world_console import FakeConsole, FakeMemory

from pokemon_agent.world import Facts, ScreenText, StepObservation, TaskScene
from pokemon_agent.world.ram import (
    W_BAG_ITEMS,
    W_NUM_BAG_ITEMS,
    W_PARTY_COUNT,
    W_PARTY_MON1_HP,
    W_PARTY_SPECIES,
    W_PLAYER_MONEY,
)
from pokemon_agent.world.scripts.control_flow import Abort
from pokemon_agent.world.scripts.engine import ScriptRun
from pokemon_agent.world.scripts.interruptions import field_policy
from pokemon_agent.world.scripts.policies import ScriptPolicy, StableWait


class ObservedConsole(FakeConsole):
    """固定屏幕序列与交互格；RAM 字节由测试给定，不启动模拟器。"""

    def __init__(self, frames: list[ScreenText], kind: str | None = None) -> None:
        super().__init__(frames)
        self.kind = kind
        self.elapsed = 0
        self.presses: list[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)
        super().press(key)

    def tick(self, frames: int) -> None:
        self.elapsed += frames

    def facing(self) -> str:
        return "east"

    def object_kind(self, x: int, y: int) -> str | None:
        return self.kind if (x, y) == (self.pos().x + 1, self.pos().y) else None


def ram_memory() -> FakeMemory:
    """现金、一个背包条目与一只精灵的固定 RAM 字节。"""
    values = {
        W_PLAYER_MONEY + 1: 0x12,
        W_PLAYER_MONEY + 2: 0x34,
        W_NUM_BAG_ITEMS: 1,
        W_BAG_ITEMS: 20,
        W_BAG_ITEMS + 1: 2,
        W_PARTY_COUNT: 1,
        W_PARTY_SPECIES: 153,
        W_PARTY_MON1_HP + 1: 18,
        W_PARTY_MON1_HP + 0x20: 5,
        W_PARTY_MON1_HP + 0x22: 20,
    }
    return FakeMemory(**{str(address): value for address, value in values.items()})


def test_each_key_keeps_a_compact_snapshot_after_existing_stable_wait() -> None:
    console = ObservedConsole(
        [ScreenText(), ScreenText(dialog_text="A", screen="A"), ScreenText(dialog_text="B")]
    )
    console.memory = ram_memory()
    policy = ScriptPolicy(wait=StableWait(poll_frames=2, stable_polls=2))
    run = ScriptRun(console, budget=3, start_map_id=12, start_pos=console.pos(), policy=policy)

    result = run.execute(["a", "a", "b"])

    assert len(result.observations) == len(console.presses) == 3
    assert [observation.step for observation in result.observations] == [1, 2, 3]
    assert [observation.dialog_text for observation in result.observations] == ["A", "B", "B"]
    assert console.elapsed == 18
    for observation in result.observations:
        assert isinstance(observation, StepObservation)
        assert observation.settled and observation.facing_object is None
        assert observation.place == console.pos() and observation.facing == "east"
        assert observation.ram is not None
        assert observation.ram.model_dump() == {
            "in_battle": False,
            "money": 1234,
            "bag": [{"item_id": 20, "quantity": 2}],
            "party": [{"species": 153, "level": 5, "hp": 18, "max_hp": 20, "status": "ok"}],
        }
        assert observation.battle_status is None


def test_compact_observation_omits_full_terrain_and_menu_diagnostics() -> None:
    console = ObservedConsole([ScreenText()])
    run = ScriptRun(console, budget=1, start_map_id=12, start_pos=console.pos())

    result = run.execute(["a"])

    assert set(result.observations[0].model_dump()) == {
        "step",
        "place",
        "facing",
        "scene",
        "overlay",
        "dialog_text",
        "options",
        "cursor",
        "screen",
        "ram",
        "facing_object",
        "battle_status",
        "settled",
    }


@pytest.mark.parametrize("kind", ["人", "门", "招牌", None])
def test_facing_object_identifies_the_adjacent_interactive_cell(kind: str | None) -> None:
    console = ObservedConsole([ScreenText()], kind=kind)
    run = ScriptRun(console, budget=1, start_map_id=12, start_pos=console.pos())

    result = run.execute(["a"])

    target = result.observations[0].facing_object
    if kind is None:
        assert target is None
    else:
        assert target is not None and target.kind == kind
        assert target.place == console.pos().step_toward("east")


@pytest.mark.parametrize("abort_on_timeout", [False, True])
def test_timeout_key_is_observed_as_unsettled(abort_on_timeout: bool) -> None:
    console = ObservedConsole([ScreenText(dialog_text="still moving")])
    policy = ScriptPolicy(wait=StableWait(timeout_frames=8, abort_on_timeout=abort_on_timeout))
    run = ScriptRun(console, budget=1, start_map_id=12, start_pos=console.pos(), policy=policy)

    if abort_on_timeout:
        with pytest.raises(Abort):
            run.press("a")
        result = run.finish(ok=False, code="step_timeout")
    else:
        result = run.execute(["a"])

    assert console.presses == ["a"] and console.elapsed == 8
    assert len(result.observations) == 1
    assert result.observations[0].settled is False
    assert result.observations[0].dialog_text == "still moving"


def test_interruption_retains_battle_snapshot_and_choice_fields() -> None:
    text = ScreenText(
        in_battle=True, has_cursor=True, options=["FIGHT", "RUN"], cursor="RUN", screen="battle"
    )
    console = ObservedConsole([ScreenText(), text])
    console.memory = FakeMemory(**{str(0xD057): 1})
    run = ScriptRun(
        console, budget=2, start_map_id=12, start_pos=console.pos(), policy=field_policy()
    )

    result = run.execute(["a", "a"])

    assert result.code == "battle_started" and console.presses == ["a"]
    (observation,) = result.observations
    assert observation.scene == TaskScene.BATTLE_MENU
    assert observation.overlay == Facts.Overlay.CHOICE
    assert observation.options == ["FIGHT", "RUN"] and observation.cursor == "RUN"
    assert observation.screen == "battle"
    assert observation.ram is not None and observation.ram.in_battle
    assert observation.battle_status is not None


def test_script_without_keys_has_no_observations() -> None:
    console = ObservedConsole([ScreenText()])
    run = ScriptRun(console, budget=1, start_map_id=12, start_pos=console.pos())

    result = run.execute([])

    assert result.observations == [] and console.presses == [] and console.elapsed == 0


def test_map_change_snapshot_is_kept_before_the_interrupt_stops_the_script() -> None:
    console = ObservedConsole([ScreenText()])
    run = ScriptRun(
        console, budget=2, start_map_id=11, start_pos=console.pos(), policy=field_policy()
    )

    result = run.execute(["a", "a"])

    assert result.code == "map_changed" and console.presses == ["a"]
    assert len(result.observations) == 1 and result.observations[0].place.map_id == 12
