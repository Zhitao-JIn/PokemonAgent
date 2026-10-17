"""掩码：`compute_action_space` 按场合把脚本条目放进 mask/entries。"""

from __future__ import annotations

from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene
from pokemon_agent.world.action_space import compute_action_space
from pokemon_agent.world.scripts.catalog import SCRIPT_SPECS
from pokemon_agent.world.scripts.scenes import SCRIPT_DEFINITIONS

FIELD_SCRIPTS = set(SCRIPT_SPECS) - set(SCRIPT_DEFINITIONS) - {"buy_item", "sell_item"}

ALL_BUTTONS = ["a", "b", "up", "down", "left", "right", "start", "select"]


def _obs(scene: TaskScene) -> TaskObservation:
    return TaskObservation(
        step=0, status="s", scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


# ---- 2. 掩码：脚本条目进 mask/entries ----


def test_action_space_walk_includes_scripts_in_mask() -> None:
    space = compute_action_space(_obs(TaskScene.WALK), ALL_BUTTONS)
    for name in FIELD_SCRIPTS:
        assert space.enabled(name), f"{name} 应在 walk 场合可用"
        entry = space.entry(name)
        assert entry is not None and entry.kind == "script"
    assert space.enabled("a")  # 键照常


def test_action_space_takeover_scene_keeps_directions_with_its_takeover_scripts() -> None:
    space = compute_action_space(_obs(TaskScene.PARTY), ALL_BUTTONS)
    assert set(space.names) == {"up", "down", "left", "right", "a", "b"}
    scripts = [entry for entry in space.entries if entry.kind == "script"]
    assert scripts
    assert all(entry.name.startswith("party_") and space.enabled(entry.name) for entry in scripts)
    assert space.enabled("a") and space.enabled("b")
    assert not space.enabled("start") and not space.enabled("select")
