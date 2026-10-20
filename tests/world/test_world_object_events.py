"""按键 → 物体事件：候选格、四种姿势判定，以及 `observe_step` 的单帧装配。"""

from __future__ import annotations

import pytest

from pokemon_agent.world import Facts, PlaceInWorld, TaskObservation, TaskPerceived, TaskScene
from pokemon_agent.world.object_events import judge_press, observe_step, press_cells

ACTOR = PlaceInWorld(map_id=12, x=13, y=8)
NORTH = PlaceInWorld(map_id=12, x=13, y=7)
EAST = PlaceInWorld(map_id=12, x=14, y=8)


def _kind_at(marks: dict[tuple[int, int], str]):
    """按 `(x, y)` 查手写表；未登记返回 None。"""

    def lookup(place: PlaceInWorld) -> str | None:
        return marks.get((place.x, place.y))

    return lookup


def _event(
    outcome: str,
    place: PlaceInWorld,
    kind: str,
    button: str,
    *,
    actor: PlaceInWorld = ACTOR,
    **extra: object,
) -> dict[str, object]:
    """完整事件字典：公共五键 + dialog 的 text / warp 的 map_id。"""
    return {
        "outcome": outcome,
        "actor_place": actor.model_dump(),
        "place": place.model_dump(),
        "object_kind": kind,
        "button": button,
        **extra,
    }


def _judge(
    button: str,
    marks: dict[tuple[int, int], str],
    *,
    facing: str = "north",
    times: int = 1,
    after: PlaceInWorld | None = ACTOR,
    dialog: str = "",
    actor: PlaceInWorld | None = ACTOR,
) -> list[dict[str, object]]:
    return judge_press(
        actor_place=actor,
        facing_before=facing,
        button=button,
        times=times,
        after_place=after,
        dialog_text=dialog,
        kind_at=_kind_at(marks),
    )


class _World:
    """两帧假 world：依次交出 before / after，并记录 step 入参。"""

    def __init__(self, before: TaskObservation, after: TaskObservation) -> None:
        self._frames = [before, after]
        self.steps: list[tuple[list[tuple[str, int]], bool]] = []

    def perceive_task(self) -> TaskPerceived:
        return TaskPerceived(observation=self._frames.pop(0), frame_png="")

    def step(self, pairs: list[tuple[str, int]], *, settle: bool = True) -> None:
        self.steps.append((pairs, settle))


def _observation(
    place: PlaceInWorld | None = ACTOR,
    *,
    facing: str = "north",
    landmarks: list[Facts.Landmark] | None = None,
    dialog: str = "",
) -> TaskObservation:
    return TaskObservation(
        step=0,
        place=place,
        status="",
        facts=Facts(facing=facing, dialog_text=dialog, landmarks=landmarks or []),
        scene=TaskScene.WALK,
    )


def _mark(kind: str, place: PlaceInWorld) -> Facts.Landmark:
    return Facts.Landmark(kind=kind, map_id=place.map_id, x=place.x, y=place.y)


# ---- O1 ----
@pytest.mark.parametrize(
    ("facing", "neighbor"),
    [
        ("north", NORTH),
        ("south", PlaceInWorld(map_id=12, x=13, y=9)),
        ("west", PlaceInWorld(map_id=12, x=12, y=8)),
        ("east", EAST),
    ],
    ids=["north", "south", "west", "east"],
)
def test_press_cells_returns_actor_and_facing_neighbor(facing: str, neighbor: PlaceInWorld) -> None:
    assert press_cells(ACTOR, facing) == [ACTOR, neighbor]


# ---- O2 ----
@pytest.mark.parametrize(
    ("dialog", "expected"),
    [
        ("你好！", _event("dialog", NORTH, "人", "a", text="你好！")),
        ("   ", _event("still", NORTH, "人", "a")),
    ],
    ids=["dialog", "still"],
)
def test_interacting_with_person_records_dialog_or_still(
    dialog: str, expected: dict[str, object]
) -> None:
    assert _judge("a", {(13, 7): "人"}, dialog=dialog) == [expected]


# ---- O3 ----
@pytest.mark.parametrize(
    ("marks", "place"),
    [
        ({(13, 6): "人"}, PlaceInWorld(map_id=12, x=13, y=6)),
        ({(13, 6): "人", (13, 7): "人"}, NORTH),
    ],
    ids=["two-cells-away", "nearer-wins"],
)
def test_counter_interaction_prefers_the_nearer_person(
    marks: dict[tuple[int, int], str], place: PlaceInWorld
) -> None:
    expected = [_event("dialog", place, "人", "a", text="欢迎！")]
    assert _judge("a", marks, dialog="欢迎！") == expected


# ---- O4 ----
@pytest.mark.parametrize(
    ("dialog", "expected"),
    [
        (
            "获得了 POKé BALL！",
            _event("dialog", EAST, "物", "right", text="获得了 POKé BALL！"),
        ),
        ("", _event("still", EAST, "物", "right")),
    ],
    ids=["pickup", "still"],
)
def test_walking_into_item_records_dialog_or_still(
    dialog: str, expected: dict[str, object]
) -> None:
    assert _judge("right", {(14, 8): "物"}, facing="east", after=EAST, dialog=dialog) == [expected]


# ---- O5 ----
def test_a_key_does_not_pick_up_an_item() -> None:
    assert _judge("a", {(13, 7): "物"}, dialog="获得了 POKé BALL！") == []


# ---- O6 ----
@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (NORTH, []),
        (PlaceInWorld(map_id=1, x=5, y=5), [_event("warp", NORTH, "门", "up", map_id=1)]),
    ],
    ids=["stops-on-door", "crosses-map"],
)
def test_entering_door_waits_or_records_map_change(
    after: PlaceInWorld, expected: list[dict[str, object]]
) -> None:
    assert _judge("up", {(13, 7): "门"}, after=after) == expected


# ---- O7 ----
@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (
            PlaceInWorld(map_id=1, x=5, y=5),
            [_event("warp", NORTH, "门", "up", actor=NORTH, map_id=1)],
        ),
        (NORTH, [_event("still", NORTH, "门", "up", actor=NORTH)]),
    ],
    ids=["warp", "still"],
)
def test_pushing_from_door_records_warp_or_still(
    after: PlaceInWorld, expected: list[dict[str, object]]
) -> None:
    assert _judge("up", {(13, 7): "门"}, actor=NORTH, after=after) == expected


# ---- O8 ----
@pytest.mark.parametrize(
    ("button", "kwargs", "marks"),
    [
        ("up", {"times": 2}, {(13, 7): "人"}),
        ("up", {"facing": "south"}, {(13, 7): "人"}),
        ("up", {"actor": None}, {}),
        ("up", {"after": None}, {}),
        ("b", {}, {(13, 7): "人"}),
        ("up", {}, {(13, 7): "石"}),
    ],
    ids=["twice", "turned-first", "no-actor", "no-after", "b-key", "boulder"],
)
def test_non_interactions_produce_no_events(
    button: str, kwargs: dict[str, object], marks: dict[tuple[int, int], str]
) -> None:
    assert _judge(button, marks, **kwargs) == []


# ---- O9 ----
@pytest.mark.parametrize(
    ("dialog", "expected"),
    [
        ("你好！", _event("dialog", NORTH, "人", "a", text="你好！")),
        ("   ", _event("still", NORTH, "人", "a")),
    ],
    ids=["dialog", "still"],
)
def test_observe_step_reads_person_events_from_landmarks(
    dialog: str, expected: dict[str, object]
) -> None:
    world = _World(
        _observation(landmarks=[_mark("人", NORTH)]),
        _observation(dialog=dialog, landmarks=[_mark("人", NORTH)]),
    )

    moved, event = observe_step(world, [("a", 1)])

    assert (moved, event) == (False, expected)


# ---- O10 ----
def test_observe_step_reports_movement_and_item_event() -> None:
    world = _World(
        _observation(facing="east", landmarks=[_mark("物", EAST)]),
        _observation(
            EAST, facing="east", landmarks=[_mark("物", EAST)], dialog="获得了 POKé BALL！"
        ),
    )

    moved, event = observe_step(world, [("right", 1)])

    assert moved is True
    assert event == _event("dialog", EAST, "物", "right", text="获得了 POKé BALL！")


# ---- O11 ----
def test_observe_step_ignores_stone_landmarks() -> None:
    world = _World(
        _observation(landmarks=[_mark("石", NORTH)]),
        _observation(dialog="推不动", landmarks=[_mark("石", NORTH)]),
    )

    assert observe_step(world, [("a", 1)]) == (False, None)


# ---- O12 ----
def test_observe_step_chain_produces_no_event() -> None:
    world = _World(_observation(), _observation())

    moved, event = observe_step(world, [("up", 1), ("up", 1)])

    assert (moved, event) == (False, None)
    assert world.steps == [([("up", 1), ("up", 1)], True)]


# ---- O13 ----
def test_observe_step_forwards_settle_false() -> None:
    world = _World(_observation(), _observation())

    moved, event = observe_step(world, [("a", 1)], settle=False)

    assert (moved, event) == (False, None)
    assert world.steps == [([("a", 1)], False)]
