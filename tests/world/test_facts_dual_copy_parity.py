"""world与ActMemory快照比较结构化字段，冻结旧键保留为extra。"""

from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import Facts, TaskObservation, TaskScene

SnapFacts = ActMemory.Observation.Facts


def live_facts() -> Facts:
    return Facts(
        scene=Facts.Scene.FIELD,
        overlay=Facts.Overlay.CHOICE,
        facing="north",
        map_id=12,
        neighbor_cells={"up": "G", "down": ".", "left": "#", "right": "N"},
        cells=["##########"] * 9,
        landmarks=[Facts.Landmark(kind="人", map_id=12, x=2, y=3)],
        options=["YES", "NO"],
        option_grid=[["YES"], ["NO"]],
        cursor_cell=(1, 0),
        option_annotations=["", "×2"],
        terrain_visible=True,
    )


def test_dual_copy_declares_the_same_structured_fields_in_order() -> None:
    assert list(Facts.model_fields) == [key for key in SnapFacts.model_fields if key != "overview"]


def test_snapshot_preserves_structured_data_byte_for_byte() -> None:
    facts = live_facts()

    snapshot = SnapFacts.model_validate_json(facts.model_dump_json())

    assert snapshot.model_dump(mode="json", exclude={"overview"}) == facts.model_dump(mode="json")


def test_unknown_frozen_keys_survive_in_both_copies() -> None:
    data = {"where": "old position", "neighbors": "old neighbors", "walk_map": "old map"}

    real, snapshot = Facts.model_validate(data), SnapFacts.model_validate(data)

    assert real.model_extra == snapshot.model_extra == data
    assert not set(data) & Facts.model_fields.keys()
    assert not set(data) & SnapFacts.model_fields.keys()


def test_snapshot_preserves_combatant_status_as_structured_data() -> None:
    data = live_facts().model_dump(mode="json")
    side = {"name": "P", "level": 5, "hp": 3, "max_hp": 10, "status": "PSN"}
    data["battle_status"] = {"mine": side, "foe": side}

    real, snapshot = Facts.model_validate(data), SnapFacts.model_validate(data)

    assert snapshot.battle_status.model_dump() == real.battle_status.model_dump()
    assert snapshot.battle_status.mine.status == "PSN"


def test_live_snapshot_contains_no_retired_text_keys() -> None:
    observation = TaskObservation(step=7, scene=TaskScene.WALK, facts=live_facts())

    snapshot = ActMemory.Observation.model_validate(observation.model_dump(mode="json"))

    assert "status" not in snapshot.model_dump()
    assert "observation_notes" not in observation.model_dump()
    assert (
        not {"where", "neighbors", "walk_map", "option_layout", "option_details"}
        & snapshot.facts.model_dump().keys()
    )


def test_legacy_facts_dump_does_not_invent_incremental_fields() -> None:
    fields = {"scene": "field", "overlay": "none", "where": "old position"}
    real, snapshot = Facts.model_validate(fields), SnapFacts.model_validate(fields)

    for name in (
        "neighbor_cells",
        "cells",
        "option_grid",
        "cursor_cell",
        "option_annotations",
        "battle_status",
        "terrain_visible",
    ):
        assert name not in real.model_dump(mode="json")
        assert name not in snapshot.model_dump(mode="json")
    assert real.model_extra["where"] == snapshot.model_extra["where"] == "old position"
