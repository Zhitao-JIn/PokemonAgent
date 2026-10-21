"""能力掩码 `compute_action_space`：命名空间、不可用键、overlay 与接管、空空间断言。"""

from __future__ import annotations

import pytest

from pokemon_agent.world import (
    BASIC_KEYS,
    OVERLAY_ACTIONS,
    Facts,
    PlaceInWorld,
    TaskObservation,
    TaskScene,
)
from pokemon_agent.world.action_space import compute_action_space
from pokemon_agent.world.scripts.catalog import script_entries

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


def _obs(scene: TaskScene, overlay: Facts.Overlay | None = None) -> TaskObservation:
    return TaskObservation(
        step=0,
        status="s",
        scene=scene,
        place=PlaceInWorld(map_id=12, x=13, y=8),
        facts=Facts(overlay=overlay),
    )


class _TakeoverFlagLiar(TaskObservation):
    """手写假件：场合是 walk（注册表里没有接管脚本），却自称被脚本接管。"""

    @property
    def covered_by_script(self) -> bool:
        return True


def test_mask_covers_the_whole_namespace_with_keys_and_scripts() -> None:
    space = compute_action_space(_obs(TaskScene.WALK), ALL_BUTTONS)

    expected = set(ALL_BUTTONS) | {entry.name for entry in script_entries("walk")}
    assert set(space.mask) == expected


def test_unavailable_key_is_listed_as_false_not_omitted() -> None:
    space = compute_action_space(_obs(TaskScene.DIALOG, Facts.Overlay.DIALOG), ALL_BUTTONS)

    assert "start" in space.mask
    assert "select" in space.mask
    assert space.mask["start"] is False
    assert space.mask["select"] is False


def test_basic_keys_stay_open_when_no_overlay_and_no_takeover() -> None:
    space = compute_action_space(_obs(TaskScene.WALK), ALL_BUTTONS)

    assert all(space.mask[key] for key in BASIC_KEYS)


def test_overlay_actions_replace_plain_keys_for_that_overlay() -> None:
    overlay = Facts.Overlay.DIALOG
    all_actions = ["a", "b", "start", "select"]
    space = compute_action_space(_obs(TaskScene.DIALOG, overlay), all_actions)

    open_keys = {name for name, enabled in space.mask.items() if enabled and name in all_actions}
    expected = (set(OVERLAY_ACTIONS[overlay]) | BASIC_KEYS) & set(all_actions)
    assert open_keys == expected


def test_takeover_scene_closes_plain_keys_except_basic_keys() -> None:
    space = compute_action_space(_obs(TaskScene.PARTY), ALL_BUTTONS)

    for key in ALL_BUTTONS:
        assert space.mask[key] is (key in BASIC_KEYS)


def test_empty_action_space_is_refused_by_assertion() -> None:
    with pytest.raises(AssertionError):
        compute_action_space(_obs(TaskScene.TITLE), [])


def test_takeover_flag_disagreeing_with_registry_is_refused() -> None:
    obs = _TakeoverFlagLiar(
        step=0,
        status="s",
        scene=TaskScene.WALK,
        place=PlaceInWorld(map_id=12, x=13, y=8),
    )

    with pytest.raises(AssertionError):
        compute_action_space(obs, ALL_BUTTONS)
