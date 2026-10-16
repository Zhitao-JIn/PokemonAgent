"""GameTools 的动作空间：`names` / `mask` / `entries` 只来自 world，game_tools 只补 prompt 文案。"""

from __future__ import annotations

import pytest

from pokemon_agent.mcpclient.action_space import action_space_for as _action_space
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.action_space import compute_action_space

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


def _obs(scene: TaskScene) -> TaskObservation:
    return TaskObservation(
        step=0, status="s", scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


def test_open_key_scene_is_world_space_plus_prompt_text() -> None:
    obs = _obs(TaskScene.WALK)
    got, world = _action_space(obs, ALL_BUTTONS), compute_action_space(obs, ALL_BUTTONS)
    assert (got.scene, got.names, got.mask, got.entries) == (
        world.scene,
        world.names,
        world.mask,
        world.entries,
    )
    assert got.descriptions and got.note and got.map_note
    assert not world.descriptions and not world.note and not world.map_note


def test_script_scene_keeps_world_directions_and_adds_prompt_text() -> None:
    obs = _obs(TaskScene.PARTY)
    got = _action_space(obs, ALL_BUTTONS)
    world = compute_action_space(obs, ALL_BUTTONS)
    assert (got.names, got.mask, got.entries) == (world.names, world.mask, world.entries)
    assert set(got.names) == {"up", "down", "left", "right", "a", "b"}
    assert got.descriptions
    assert got.enabled("a") and got.enabled("b")
    assert not got.enabled("start") and not got.enabled("select")


def test_mask_names_every_key_and_matches_the_available_ones() -> None:
    got = _action_space(_obs(TaskScene.WALK), ALL_BUTTONS)
    assert set(ALL_BUTTONS) <= set(got.mask)
    assert {key for key in ALL_BUTTONS if got.enabled(key)} == set(got.names)


@pytest.mark.parametrize("scene", list(TaskScene))
def test_every_scene_exposes_basic_keys_in_its_world_mask(scene: TaskScene) -> None:
    from pokemon_agent.world import BASIC_KEYS, Facts

    for overlay in Facts.Overlay:
        observation = _obs(scene).model_copy(update={"facts": Facts(overlay=overlay)})

        space = compute_action_space(observation, ALL_BUTTONS)

        assert set(space.names) >= BASIC_KEYS
        assert all(space.enabled(key) for key in BASIC_KEYS)
        assert {entry.name for entry in space.entries if entry.kind == "key"} == set(space.names)
        assert not space.enabled("select")
        assert space.enabled("start") == (
            not observation.covered_by_script
            and overlay in {Facts.Overlay.NONE, Facts.Overlay.CHOICE}
        )
