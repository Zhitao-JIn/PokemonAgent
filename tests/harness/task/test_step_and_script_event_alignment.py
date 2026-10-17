"""事件流对齐钉子：**同一操作序列，step 路径与脚本路径产出逐字段一致的事件。**

- 两路径对齐钉子（判定收进 `world/object_events.py` 后的结构性保证，这里钉死）；
- 入流过滤：普通移动零事件、blocked 零事件、门 warp 入流；
- `rules.stamp_events` 补三章（episode_id/step）与三族落库类型组装。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.harness.task.perceive.store_object_semantic_memory.rules import stamp_events
from pokemon_agent.world import PlaceInWorld, ScreenText, TaskObservation, TaskScene
from pokemon_agent.world.interface import Facts
from pokemon_agent.world.object_events import judge_press
from pokemon_agent.world.scripts.engine import ScriptRun

MAP = 12
ACTOR = PlaceInWorld(map_id=MAP, x=13, y=8)
PERSON = PlaceInWorld(map_id=MAP, x=13, y=7)  # 面朝 north 的 facing 邻格
DOOR = PlaceInWorld(map_id=MAP, x=13, y=8)  # 脚下这格是门


def _obs(
    *,
    place: PlaceInWorld,
    facing: str = "north",
    dialog: str = "",
    person: bool = False,
    door: bool = False,
) -> TaskObservation:
    marks: list[Facts.Landmark] = []
    if person:
        marks.append(Facts.Landmark(kind="人", map_id=place.map_id, x=PERSON.x, y=PERSON.y))
    if door:
        marks.append(Facts.Landmark(kind="门", map_id=place.map_id, x=DOOR.x, y=DOOR.y))
    return TaskObservation(
        step=0,
        status="s",
        scene=TaskScene.WALK,
        place=place,
        facts=Facts(landmarks=marks, facing=facing, dialog_text=dialog),
    )


class _AlignConsole:
    """脚本路径替身：object_kind 表 + 按键后可选换图 / 弹对话。"""

    def __init__(
        self,
        *,
        kind_map: dict[tuple[int, int], str],
        facing: str = "north",
        dialog: str = "",
        after_map_id: int | None = None,
    ) -> None:
        self._kind_map = kind_map
        self._facing = facing
        self._dialog = dialog
        self._map_id = MAP
        self._after_map_id = after_map_id
        from collections import defaultdict

        self.memory: Any = defaultdict(int)
        self.rom = b""
        self._x, self._y = ACTOR.x, ACTOR.y

    def press(self, key: str) -> None:
        if self._after_map_id is not None:
            self._map_id = self._after_map_id

    def tick(self, frames: int) -> None:  # noqa: ARG002
        pass

    def read(self) -> ScreenText:
        return ScreenText(dialog_text=self._dialog)

    def map_id(self) -> int:
        return self._map_id

    def pos(self) -> PlaceInWorld:
        return PlaceInWorld(map_id=self._map_id, x=self._x, y=self._y)

    def facing(self) -> str:
        return self._facing

    def object_kind(self, x: int, y: int) -> str | None:
        return self._kind_map.get((x, y))


def _script_event(console: _AlignConsole, button: str) -> dict[str, Any] | None:
    from pokemon_agent.world.scripts.policies import ScriptPolicy

    run = ScriptRun(
        console,
        budget=5,
        start_map_id=MAP,
        start_pos=console.pos(),
        policy=ScriptPolicy(collect_world_events=True),
    )
    run.press(button)
    return run.events[0] if run.events else None


# ---- ① 对齐钉子：a 键对"人"弹对话 ----


def test_dialog_event_identical_across_paths() -> None:
    # step 路径：world 侧按 before 帧 landmarks 判定。
    before = _obs(place=ACTOR, person=True)
    after = _obs(place=ACTOR, person=True, dialog="你好！")
    step_event = judge_press(
        actor_place=before.place,
        facing_before=before.facts.facing,
        button="a",
        times=1,
        after_place=after.place,
        dialog_text=after.facts.dialog_text,
        kind_at=lambda p: {(PERSON.x, PERSON.y): "人"}.get((p.x, p.y)),
    )[0]

    # 脚本路径：ScriptRun.press 逐键调同一裁判。
    console = _AlignConsole(kind_map={(PERSON.x, PERSON.y): "人"}, dialog="你好！")
    script_event = _script_event(console, "a")

    assert step_event == script_event
    assert step_event["outcome"] == "dialog"
    assert step_event["object_kind"] == "人"
    assert step_event["place"] == PERSON.model_dump()


# ---- ② 对齐钉子：踩着"门"朝外按 → warp ----


def test_warp_event_identical_across_paths() -> None:
    after_place = PlaceInWorld(map_id=1, x=13, y=8)
    before = _obs(place=DOOR, door=True)
    step_event = judge_press(
        actor_place=before.place,
        facing_before=before.facts.facing,
        button="up",
        times=1,
        after_place=after_place,
        dialog_text="",
        kind_at=lambda p: {(DOOR.x, DOOR.y): "门"}.get((p.x, p.y)),
    )[0]

    console = _AlignConsole(kind_map={(DOOR.x, DOOR.y): "门"}, after_map_id=1)
    script_event = _script_event(console, "up")

    assert step_event == script_event
    assert step_event["outcome"] == "warp"
    assert step_event["map_id"] == 1


# ---- ③ 入流过滤 ----


def test_plain_movement_and_blocked_produce_no_events() -> None:
    # 普通移动（无交互物）零事件；blocked（没动、没交互物）零事件。
    for after_place in (PlaceInWorld(map_id=MAP, x=13, y=7), ACTOR):
        events = judge_press(
            actor_place=ACTOR,
            facing_before="north",
            button="up",
            times=1,
            after_place=after_place,
            dialog_text="",
            kind_at=lambda p: None,  # noqa: ARG005
        )
        assert events == []


def test_turning_first_produces_no_events() -> None:
    # 先转向再走不算一次干净的碰撞尝试（facing_before ≠ 按键朝向）。
    events = judge_press(
        actor_place=ACTOR,
        facing_before="south",
        button="up",
        times=1,
        after_place=ACTOR,
        dialog_text="",
        kind_at=lambda p: {(PERSON.x, PERSON.y): "人"}.get((p.x, p.y)),  # noqa: ARG005
    )
    assert events == []


# ---- ④ stamp_events：补三章 + 三族组装 ----


def test_stamp_events_builds_typed_records() -> None:
    dialog = {
        "outcome": "dialog",
        "actor_place": ACTOR.model_dump(),
        "place": PERSON.model_dump(),
        "object_kind": "人",
        "button": "up",
        "text": "你好！",
    }
    warp = {
        "outcome": "warp",
        "actor_place": DOOR.model_dump(),
        "place": DOOR.model_dump(),
        "object_kind": "门",
        "button": "up",
        "map_id": 1,
    }
    still = {
        "outcome": "still",
        "actor_place": ACTOR.model_dump(),
        "place": PERSON.model_dump(),
        "object_kind": "招牌",
        "button": "up",
    }
    events = stamp_events([dialog, warp, still], episode_id="ep-1", step=7)
    assert [type(e).__name__ for e in events] == [
        "ObjectDialogEvent",
        "ObjectWarpEvent",
        "ObjectStillEvent",
    ]
    for e in events:
        assert e.episode_id == "ep-1" and e.step == 7
    assert events[0].text == "你好！"
    assert events[1].map_id == 1
