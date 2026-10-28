"""观察差异是可复用的机械事实，未稳定文字不能成为证据。"""

from pokemon_agent.memory.changes import changes
from pokemon_agent.world import StepObservation


def observation(step: int, **updates: object) -> StepObservation:
    values: dict[str, object] = {
        "step": step,
        "place": {"map_id": 1, "x": 4, "y": 4},
        "facing": "north",
        "scene": "walk",
        "overlay": "none",
        "ram": {"in_battle": False, "money": 100, "bag": [], "party": []},
    }
    values.update(updates)
    return StepObservation.model_validate(values)


def test_all_mechanical_changes_keep_step_place_and_object() -> None:
    previous = observation(1)
    current = observation(
        2,
        place={"map_id": 2, "x": 5, "y": 6},
        facing_object={"kind": "人", "place": {"map_id": 2, "x": 5, "y": 5}},
        dialog_text="Hello\nShop",
        scene="dialog",
        overlay="dialog",
        ram={
            "in_battle": False,
            "money": 50,
            "bag": [{"item_id": 20, "quantity": 1}],
            "party": [{"species": 153, "level": 5, "hp": 10, "max_hp": 20, "status": "ok"}],
        },
    )

    result = changes(previous, current)

    assert [c.kind for c in result] == [
        "dialog_line",
        "dialog_line",
        "warp",
        "money",
        "bag",
        "party",
        "scene",
    ]
    assert [c.text for c in result[:2]] == ["Hello", "Shop"]
    assert all(c.step == 2 and c.place.map_id == 2 and c.object.kind == "人" for c in result)
    assert "100" in result[3].text and "50" in result[3].text
    assert "20" in result[4].text and "153" in result[5].text


def test_repeated_line_after_another_line_is_a_new_dialog_occurrence() -> None:
    first = observation(1, dialog_text="Hello")
    second = observation(2, dialog_text="Other")
    third = observation(3, dialog_text="Hello")
    fourth = observation(4, dialog_text="Hello", place={"map_id": 1, "x": 5, "y": 4})

    result = changes(first, second) + changes(second, third) + changes(third, fourth)

    assert [(c.kind, c.text) for c in result] == [
        ("dialog_line", "Other"),
        ("dialog_line", "Hello"),
    ]


def test_unsettled_text_is_suppressed_but_other_changes_are_kept() -> None:
    before = observation(1, dialog_text="Before")
    after = observation(
        2,
        settled=False,
        dialog_text="Half tex",
        place={"map_id": 2, "x": 4, "y": 4},
        scene="dialog",
        ram={"in_battle": False, "money": 200, "bag": [], "party": []},
    )

    result = changes(before, after)

    assert [c.kind for c in result] == ["warp", "money", "scene"]
    assert all("Half tex" not in c.text for c in result)
