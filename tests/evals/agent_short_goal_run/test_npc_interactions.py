"""NPC interaction scoring derives evidence from action-memory observations."""

from __future__ import annotations

from evals.agent_short_goal_run.scorer.npc_interactions import interacted_npcs
from pokemon_agent.direct.trace.content import OtherContent
from tests.evals.agent_short_goal_run.test_evals_checks import _event, frame, stream


def _observation(
    step: int,
    text: str,
    *,
    kind: str | None = "人",
    settled: bool = True,
) -> dict:
    """一帧脚本内观察，NPC 格位固定在主角朝向格。"""
    result = {
        "step": step,
        "place": {"map_id": 1, "x": 1, "y": 1},
        "facing": "east",
        "scene": "walk",
        "overlay": "dialog" if text else "none",
        "dialog_text": text,
        "settled": settled,
    }
    if kind is not None:
        result["facing_object"] = {"kind": kind, "place": {"map_id": 1, "x": 2, "y": 1}}
    return result


def _act_event(
    *, before_text: str = "", observations: list[dict], after_text: str = "", uuid: str = "act"
):
    before = {
        "step": 0,
        "place": {"map_id": 1, "x": 1, "y": 1},
        "facts": {"dialog_text": before_text, "scene": "walk", "overlay": "none"},
    }
    after = _observation(len(observations) + 1, after_text)
    content = OtherContent(
        before=before,
        action="script:talk",
        observations=observations,
        after=after,
        outcome=None,
    )
    return _event("write_act_memory", 2, content).model_copy(update={"uuid": uuid})


def test_a_single_npc_dialog_line_counts_as_one_interaction() -> None:
    events = stream(
        frame(1, people=((2, 1),)),
        _act_event(
            observations=[_observation(1, "Hello."), _observation(2, "Hello.")],
            after_text="Hello.",
        ),
    )

    interacted = interacted_npcs(events, ["r-ep1"])

    assert interacted == {(1, 2, 1): "act"}


def test_a_dialog_line_in_script_internal_observations_counts() -> None:
    events = stream(
        frame(1, people=((2, 1),)),
        _act_event(observations=[_observation(1, "Hello.")], after_text="Hello."),
    )

    assert interacted_npcs(events, ["r-ep1"]) == {(1, 2, 1): "act"}


def test_dialog_from_a_non_person_facing_object_does_not_count() -> None:
    events = stream(
        frame(1, people=((2, 1),)),
        _act_event(observations=[_observation(1, "It is a sign.", kind="招牌")]),
    )

    assert interacted_npcs(events, ["r-ep1"]) == {}


def test_settled_false_text_is_not_counted_by_the_changes_chain() -> None:
    events = stream(
        frame(1, people=((2, 1),)),
        _act_event(
            observations=[_observation(1, "Half a line.", settled=False)],
            after_text="Half a line.",
        ),
    )

    assert interacted_npcs(events, ["r-ep1"]) == {}


def test_dialog_without_facing_object_does_not_count() -> None:
    events = stream(
        frame(1, people=((2, 1),)),
        _act_event(observations=[_observation(1, "Hello.", kind=None)]),
    )

    assert interacted_npcs(events, ["r-ep1"]) == {}
