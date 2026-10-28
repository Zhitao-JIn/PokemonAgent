"""机械判据的用法示范：每条判据一个正例、一个反例，事件流手工拼成与落盘同形的类型化账。

反例优先取 `docs/experiments/0827-knowledge-baseline.md` 里 judge 真实犯过的错——
我们的判据读游戏变量，不该重犯：
把**我方** HP 下降当成对手受伤、把 `Choose a POKéMON.` 当成选项、看到致谢台词就当买成了。
"""

from __future__ import annotations

import pytest

from evals.agent_short_goal_run.dataset import load
from evals.agent_short_goal_run.dataset.schemas import EvalSample, SampleStart
from evals.agent_short_goal_run.scorer import RULES, RunStream, judge
from evals.runconfig import load_config
from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import (
    ActCallContent,
    EpisodeStartContent,
    EventMeta,
    OtherContent,
    SenseFrameContent,
)
from pokemon_agent.world import Facts, PlaceInWorld, RamReadout
from pokemon_agent.world.interface import (
    BagItem,
    BattleStatus,
    Combatant,
    DecodedText,
    MenuVars,
    PartyMon,
)
from pokemon_agent.world.items import item_id

GOAL = "knowledge_sample"


def frame(
    n: int,
    *,
    map_id: int = 1,
    y: int = 5,
    dialog: str = "",
    options: tuple[str, ...] = (),
    cursor: str | None = None,
    overlay: Facts.Overlay | None = None,
    annotations: tuple[str, ...] = (),
    source: str = "decode",
    in_battle: bool = False,
    money: int = 3000,
    bag: dict[int, int] | None = None,
    party: tuple[tuple[int, int], ...] = ((20, 20),),
    people: tuple[tuple[int, int], ...] = (),
    my_hp: int = 20,
    foe_hp: int = 15,
    x: int = 3,
    status: tuple[str, ...] | None = None,
) -> ParsedEvent:
    """一帧 `sense_frame`：位置、文字、内存读数都可指定。

    `source="vlm"` 模拟 episode 层看档帧上视觉抄出了字、屏幕解码却没有：文字只进 `facts`，
    `ram.decoded` 为空——判据读的是后者。
    """
    facts = Facts(
        map_id=map_id,
        dialog_text=dialog,
        options=list(options),
        cursor=cursor,
        landmarks=[
            Facts.Landmark(kind="人", map_id=map_id, x=x, y=person_y) for x, person_y in people
        ],
        overlay=overlay,
        option_annotations=list(annotations),
    )
    battle = (
        BattleStatus(
            mine=Combatant(name="BULBASAUR", level=5, hp=my_hp, max_hp=20, status="ok"),
            foe=Combatant(name="RATTATA", level=3, hp=foe_hp, max_hp=15, status="ok"),
        )
        if in_battle
        else None
    )
    ram = RamReadout(
        in_battle=in_battle,
        covered=True,
        text_source=source,  # type: ignore[arg-type]
        menu=MenuVars(current_item=0, max_item=0, top_x=0),
        money=money,
        bag=[BagItem(item_id=i, quantity=q) for i, q in (bag or {}).items()],
        party=[
            PartyMon(
                species=153,
                level=5,
                hp=h,
                max_hp=m,
                status=status[i] if status is not None else "ok",
            )
            for i, (h, m) in enumerate(party)
        ],
        battle=battle,
        decoded=DecodedText(dialog_text=dialog, options=list(options), cursor=cursor or "")
        if source == "decode"
        else DecodedText(dialog_text="", options=[], cursor=""),
    )
    content = SenseFrameContent(
        status="s", facts=facts, done=False,
        place=PlaceInWorld(map_id=map_id, x=x, y=y), ram=ram,
    )  # fmt: skip
    return _event("sense_frame", n, content)


def _event(kind: str, n: int, content: object) -> ParsedEvent:
    """一条账，挂在目标那一局上。"""
    meta = EventMeta(run_id="r", branch="b1", source="t", episode_id="r-ep1", task_id="t1", step=n)
    return ParsedEvent(
        uuid=f"u{n}",
        kind=kind,
        type="view",
        started_at=float(n),
        ended_at=float(n),
        meta=meta,
        content=content,
    )  # type: ignore[arg-type]


def write_act_memory_event(
    n: int,
    person: tuple[int, int],
    *,
    text: str = "Hello.",
    previous_text: str = "",
    object_kind: str | None = "人",
    settled: bool = True,
) -> ParsedEvent:
    """一条有结构化观察的动作记忆写账。"""
    actor = {"map_id": 1, "x": 1, "y": 1}
    target = {"map_id": 1, "x": person[0], "y": person[1]}
    before = {
        "step": n * 2 - 1,
        "place": actor,
        "facts": {"dialog_text": previous_text, "scene": "walk", "overlay": "none"},
    }
    after = {
        "step": n * 2,
        "place": actor,
        "scene": "walk",
        "overlay": "dialog",
        "dialog_text": text,
        "facing_object": (
            {"kind": object_kind, "place": target} if object_kind is not None else None
        ),
        "settled": settled,
    }
    return _event(
        "write_act_memory",
        n,
        OtherContent(before=before, action="a", after=after, observations=[], outcome=None),
    )


def stream(*frames: ParsedEvent) -> RunStream:
    """一局：开局账 + 这些帧。"""
    start = EpisodeStartContent(goal_id=GOAL, goal="g", success_criteria="c", max_steps=15)
    return RunStream([_event("episode_start", 0, start), *frames])


def _mid_frame(n: int, map_id: int, **kwargs: object) -> ParsedEvent:
    """中期规则使用的合成 RAM 帧。"""
    return frame(n, map_id=map_id, **kwargs)  # type: ignore[arg-type]


def _observation_event(
    n: int, dialog: str, *, observation_map_id: int | None = None
) -> ParsedEvent:
    """脚本内逐键观察里出现的解码对话。"""
    event = _event(
        "write_act_memory",
        n,
        OtherContent(
            before={"step": n * 2 - 1, "place": {"map_id": 42, "x": 1, "y": 1}, "facts": {}},
            action="a",
            after={
                "step": n * 2,
                "place": {"map_id": 42, "x": 1, "y": 1},
                "scene": "walk",
                "overlay": "dialog",
                "dialog_text": dialog,
                "facing_object": None,
                "settled": True,
            },
            observations=(
                [
                    {
                        "step": n * 2,
                        "place": {"map_id": observation_map_id, "x": 1, "y": 1},
                        "facts": {},
                    }
                ]
                if observation_map_id is not None
                else []
            ),
            outcome=None,
        ),
    )
    event.uuid = f"dialog-{n}"
    event.ended_at = float(n) / 100
    return event


def sample(check_id: str) -> EvalSample:
    """只有 `check_id` 要紧的样本。"""
    return EvalSample(
        sample_id=GOAL, dataset_version="v1", category="x",
        start=SampleStart(kind="archive", archive="s", source_state="s.state", source_sha256="h"),
        goal="g", success_criteria="c", max_steps=15, behavior="b", check_id=check_id,
        rubric=[], red_lines=[], k_metric="pass_hat_k", split="val",
    )  # fmt: skip


CASES = {
    "map_changed": (
        [frame(1, map_id=1), frame(2, map_id=40)],
        [frame(1, map_id=1), frame(2, map_id=1)],
    ),
    "reach_map12_y14": (
        [frame(1, map_id=12, y=12), frame(2, map_id=12, y=14)],
        [frame(1, map_id=12, y=12), frame(2, map_id=12, y=13)],
    ),
    "dialog_opened": (
        [frame(1), frame(2, dialog="Hey! You came from PALLET TOWN?")],
        [frame(1), frame(2, dialog="Hey!", source="vlm"), frame(3)],
    ),
    "dialog_finished": (
        [frame(1, dialog="Hey!"), frame(2, dialog="")],
        [frame(1, dialog="Hey!"), frame(2, dialog="...more")],
    ),
    "shop_menu_opened": (
        [
            frame(
                1,
                options=("BUY", "SELL", "QUIT"),
                cursor="BUY",
                overlay=Facts.Overlay.CHOICE,
            )
        ],
        [frame(1, dialog="Hi there! May I help you?"), frame(2)],
    ),
    "shop_list_opened": (
        [
            frame(1),
            frame(2, options=("POKé BALL", "CANCEL"), cursor="POKé BALL", annotations=("¥200",)),
        ],
        [frame(1), frame(2, options=("BUY", "SELL", "QUIT"), cursor="BUY")],
    ),
    "shop_item_selected": (
        [frame(1), frame(2, options=("YES", "NO"), cursor="YES")],
        [
            frame(1),
            frame(2, options=("POKé BALL", "CANCEL"), cursor="POKé BALL", annotations=("¥200",)),
        ],
    ),
    "shop_bought": (
        [_event("act_call", 1, ActCallContent(script="buy_item", ok="true", code="ok"))],
        [
            _event(
                "act_call", 1, ActCallContent(script="buy_item", ok="false", code="verify_failed")
            )
        ],
    ),
    "shop_all_npcs_interacted": (
        [
            frame(1, people=((2, 5), (4, 3))),
            write_act_memory_event(2, (2, 5)),
            write_act_memory_event(3, (4, 3)),
        ],
        [
            frame(1, people=((2, 5), (4, 3))),
            write_act_memory_event(2, (2, 5)),
        ],
    ),
    "shop_two_npcs_interacted": (
        [
            frame(1, people=((2, 5), (4, 3), (6, 4))),
            write_act_memory_event(2, (2, 5)),
            write_act_memory_event(3, (4, 3)),
        ],
        [
            frame(1, people=((2, 5), (4, 3), (6, 4))),
            write_act_memory_event(2, (2, 5)),
        ],
    ),
    "shop_cancelled": (
        [
            frame(1, options=("YES", "NO")),
            frame(2, options=("POKé BALL",), annotations=("¥200",)),
        ],
        [
            frame(1, money=3000, options=("YES", "NO")),
            frame(2, money=2800, options=("POKé BALL",), annotations=("¥200",)),
        ],
    ),
    "battle_started": (
        [frame(1), frame(2, in_battle=True)],
        [frame(1), frame(2)],
    ),
    "cursor_on_run": (
        [frame(1, in_battle=True, options=("FIGHT", "PKMN", "ITEM", "RUN"), cursor="RUN")],
        [frame(1, in_battle=True, options=("FIGHT", "PKMN", "ITEM", "RUN"), cursor="ITEM")],
    ),
    "move_list_opened": (
        [frame(1, in_battle=True, options=("TACKLE", "GROWL"), cursor="TACKLE")],
        [frame(1, in_battle=True, options=("POTION", "CANCEL"), cursor="POTION")],
    ),
    "party_list_opened_in_battle": (
        [
            frame(
                1,
                in_battle=True,
                options=("BULBASAUR", "PIDGEY"),
                cursor="BULBASAUR",
                party=((20, 20), (15, 20)),
            ),
        ],
        [
            frame(
                1,
                in_battle=True,
                options=("FIGHT", "PKMN", "ITEM", "RUN"),
                party=((20, 20),) * 4,
            ),
            frame(
                2,
                in_battle=True,
                options=("POTION", "CANCEL"),
                party=((20, 20), (15, 20)),
            ),
            frame(
                3,
                in_battle=True,
                options=(" tackle ", "growl"),
                party=((20, 20), (15, 20)),
            ),
            frame(4, in_battle=True, options=("BULBASAUR", "PIDGEY")),
        ],
    ),
    "move_used": (
        [frame(1, in_battle=True, foe_hp=15), frame(2, in_battle=True, foe_hp=11)],
        [
            frame(1, in_battle=True, foe_hp=15, my_hp=20),
            frame(2, in_battle=True, foe_hp=15, my_hp=14),
        ],
    ),
    "bag_opened_in_battle": (
        [frame(1, in_battle=True, options=("POTION", "CANCEL"), cursor="POTION")],
        [frame(1, in_battle=True, dialog="Choose a POKéMON.")],
    ),
    "run_attempted": (
        [frame(1, in_battle=True), frame(2, in_battle=False)],
        [
            frame(1, in_battle=True),
            frame(2, in_battle=True, options=("FIGHT", "PKMN", "ITEM", "RUN")),
        ],
    ),
    "foe_hp_dropped": (
        [frame(1, in_battle=True, foe_hp=15), frame(2, in_battle=True, foe_hp=9)],
        [
            frame(1, in_battle=True, foe_hp=15, my_hp=20),
            frame(2, in_battle=True, foe_hp=15, my_hp=12),
        ],
    ),
    "ball_thrown": (
        [
            frame(1, bag={4: 3}),
            frame(2, bag={4: 3}, dialog="Aww! It appeared to be caught!"),
        ],
        [
            frame(1, bag={4: 3}),
            frame(2, bag={4: 3}, dialog="Darn! The POKéMON broke free!", source="vlm"),
        ],
    ),
    "party_healed": (
        [
            frame(1, party=((5, 25),)),
            frame(2, party=((25, 25),), dialog="We hope to see you again!"),
        ],
        [
            frame(1, party=((5, 25),)),
            frame(2, party=((5, 25),), dialog="We hope to see you again!"),
        ],
    ),
    "walk_to_pallet": (
        [_mid_frame(1, 1), _mid_frame(2, 12), _mid_frame(3, 0), _mid_frame(4, 40)],
        [_mid_frame(1, 1), _mid_frame(2, 1)],
    ),
    "heal_buy_return": (
        [
            _mid_frame(
                1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}, x=20, y=26
            ),
            _mid_frame(2, 41, party=((20, 20),), money=2000, bag={item_id("POKé BALL"): 4}, x=8),
            _mid_frame(
                3, 1, party=((20, 20),), money=1600, bag={item_id("POKé BALL"): 6}, x=20, y=26
            ),
        ],
        [
            _mid_frame(
                1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}, x=20, y=26
            ),
            _mid_frame(
                2, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}, x=20, y=26
            ),
        ],
    ),
    "catch_then_heal": (
        [
            _mid_frame(1, 12, in_battle=True, party=((12, 25),), foe_hp=10),
            _mid_frame(
                2,
                12,
                in_battle=True,
                party=((12, 25), (8, 12)),
                foe_hp=10,
                dialog="All right! PIDGEY was caught!",
            ),
            _mid_frame(3, 41, party=((25, 25), (12, 12))),
            _mid_frame(4, 1, party=((25, 25), (12, 12))),
        ],
        [
            _mid_frame(1, 12, in_battle=True, party=((12, 25),), foe_hp=10),
            _mid_frame(2, 12, in_battle=True, party=((12, 25),), foe_hp=10),
        ],
    ),
    "customer_hint_purchase": (
        [
            _observation_event(1, "This shop sells many ANTIDOTEs."),
            _observation_event(2, "No! POTIONs are all sold out."),
            _mid_frame(1, 42, party=((10, 20),), money=3000, bag={}),
            _mid_frame(2, 41, party=((20, 20),), money=3000, bag={}),
            _mid_frame(3, 42, party=((20, 20),), money=2900, bag={item_id("ANTIDOTE"): 1}),
        ],
        [
            _mid_frame(1, 42, party=((10, 20),), money=3000, bag={}),
            _mid_frame(2, 41, party=((20, 20),), money=3000, bag={}),
            _mid_frame(3, 42, party=((20, 20),), money=3000, bag={}),
        ],
    ),
    "cure_poison_budget": (
        [
            _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
            _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=1900),
            _mid_frame(3, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1900),
        ],
        [
            _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
            _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
        ],
    ),
}
"""判据 → （正例帧，反例帧）。反例里带台词的几条，就是 judge 当年被台词骗到的样子。"""


def test_every_registered_rule_has_a_positive_and_a_negative_example() -> None:
    assert set(CASES) == set(RULES)


@pytest.mark.parametrize("check_id", sorted(CASES))
def test_positive_example_passes(check_id: str) -> None:
    good, _bad = CASES[check_id]

    verdict = judge(stream(*good), sample(check_id))

    assert verdict.outcome == "pass", verdict.reason
    assert verdict.evidence, "判成要给证据帧"


@pytest.mark.parametrize("check_id", sorted(CASES))
def test_negative_example_fails(check_id: str) -> None:
    _good, bad = CASES[check_id]

    verdict = judge(stream(*bad), sample(check_id))

    assert verdict.outcome == "fail", verdict.reason


def test_text_from_vision_is_never_taken_as_truth() -> None:
    only_vision = stream(frame(1), frame(2, dialog="Hey!", source="vlm"))

    verdict = judge(only_vision, sample("dialog_finished"))

    assert verdict.outcome == "fail", "视觉给的对话不算出现过"
    vision_dialog = stream(frame(1), frame(2, dialog="Hey!", source="vlm"))
    assert judge(vision_dialog, sample("dialog_opened")).outcome == "fail"


def test_party_list_without_decoded_frames_is_unjudgeable() -> None:
    verdict = judge(stream(), sample("party_list_opened_in_battle"))

    assert verdict.outcome == "unjudgeable"


def test_shop_menu_is_unjudgeable_when_only_the_previous_frame_is_decoded() -> None:
    previous_menu = frame(
        1,
        options=("BUY", "SELL", "QUIT"),
        cursor="BUY",
        overlay=Facts.Overlay.CHOICE,
    )
    current_without_decode = frame(2, source="vlm", overlay=Facts.Overlay.CHOICE)

    verdict = judge(stream(previous_menu, current_without_decode), sample("shop_menu_opened"))

    assert verdict.outcome == "unjudgeable"


def test_pokemon_switch_sample_has_a_registered_mechanical_rule() -> None:
    samples = load("v20261028_short_frozen", rule_ids=set(RULES))
    switch = next(s for s in samples if s.sample_id == "knowledge_battle_pokemon_switch")

    assert switch.check_id == "party_list_opened_in_battle"
    assert switch.check_id in RULES


def test_configured_dataset_has_registered_checks_with_positive_and_negative_examples() -> None:
    samples = load(str(load_config()["version"]), rule_ids=set(RULES))

    assert samples
    assert all(sample.check_id in RULES and sample.check_id in CASES for sample in samples)


@pytest.mark.parametrize(
    ("check_id", "events", "reason_part"),
    [
        ("walk_to_pallet", [_mid_frame(1, 1), _mid_frame(2, 12)], "没到真新镇"),
        (
            "walk_to_pallet",
            [_mid_frame(1, 1), _mid_frame(2, 12), _mid_frame(3, 0)],
            "没进入大木研究所",
        ),
        (
            "walk_to_pallet",
            [
                _mid_frame(1, 1),
                _mid_frame(2, 12),
                _mid_frame(3, 0),
                _mid_frame(4, 40, options=("YES", "NO")),
            ],
            "选项",
        ),
        (
            "heal_buy_return",
            [
                _mid_frame(1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(2, 1, party=((20, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
            ],
            "从未",
        ),
        (
            "heal_buy_return",
            [
                _mid_frame(1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(2, 41, party=((20, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(3, 1, party=((20, 20),), money=1700, bag={item_id("POKé BALL"): 5}),
            ],
            "花费",
        ),
        (
            "heal_buy_return",
            [
                _mid_frame(1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(2, 1, party=((20, 20),), money=1600, bag={item_id("POKé BALL"): 6}),
                _mid_frame(3, 41, party=((20, 20),), money=1600, bag={item_id("POKé BALL"): 6}),
            ],
            "先买后治",
        ),
        (
            "heal_buy_return",
            [
                _mid_frame(1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(2, 41, party=((20, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(3, 2, party=((20, 20),), money=1600, bag={item_id("POKé BALL"): 6}),
            ],
            "回到起点",
        ),
        (
            "heal_buy_return",
            [
                _mid_frame(1, 1, party=((10, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(2, 41, party=((20, 20),), money=2000, bag={item_id("POKé BALL"): 4}),
                _mid_frame(
                    3, 1, party=((20, 20),), money=1600, bag={item_id("POKé BALL"): 6, 5: 1}
                ),
            ],
            "背包",
        ),
        (
            "catch_then_heal",
            [
                _mid_frame(1, 12, in_battle=True, party=((10, 20),), foe_hp=0),
                _mid_frame(2, 12, party=((20, 20), (5, 10))),
            ],
            "打倒了",
        ),
        (
            "catch_then_heal",
            [
                _mid_frame(1, 12, in_battle=True, party=((10, 20),), foe_hp=10),
                _mid_frame(
                    2,
                    12,
                    dialog="All right! PIDGEY was caught!",
                    party=((20, 20), (10, 10)),
                ),
                _mid_frame(3, 41, party=((20, 20), (10, 10))),
                _mid_frame(4, 1, party=((20, 20), (10, 10)), options=("YES", "NO")),
            ],
            "终局仍在战斗、选项或起名界面",
        ),
        (
            "catch_then_heal",
            [
                _mid_frame(1, 12, in_battle=True, party=((10, 20),), foe_hp=10),
                _mid_frame(
                    2, 12, dialog="All right! PIDGEY was caught!", party=((20, 20), (5, 10))
                ),
                _mid_frame(3, 1, party=((20, 20), (5, 10))),
            ],
            "没有在地图 41",
        ),
        (
            "catch_then_heal",
            [
                _mid_frame(1, 12, in_battle=True, party=((10, 20),), foe_hp=10),
                _mid_frame(2, 41, party=((20, 20),), dialog="All right! PIDGEY was caught!"),
                _mid_frame(3, 1, party=((20, 20), (5, 10))),
            ],
            "先治后抓",
        ),
        (
            "catch_then_heal",
            [
                _mid_frame(1, 12, in_battle=True, party=((10, 20),), foe_hp=0),
                _mid_frame(
                    2, 12, in_battle=True, dialog="All right! PIDGEY was caught!", party=((10, 20),)
                ),
                _mid_frame(3, 41, party=((20, 20), (10, 10))),
            ],
            "打倒了",
        ),
        (
            "customer_hint_purchase",
            [
                _mid_frame(1, 42, party=((10, 20),), money=3000),
                _mid_frame(2, 41, party=((20, 20),), money=3000),
                _mid_frame(3, 42, party=((20, 20),), money=2900, bag={item_id("ANTIDOTE"): 1}),
            ],
            "缺一句",
        ),
        (
            "customer_hint_purchase",
            [
                _observation_event(4, "This shop sells many ANTIDOTEs."),
                _observation_event(5, "No! POTIONs are all sold out."),
                _mid_frame(1, 42, party=((10, 20),), money=3000),
                _mid_frame(2, 42, party=((10, 20),), money=3000),
                _mid_frame(3, 42, party=((20, 20),), money=2900, bag={item_id("ANTIDOTE"): 1}),
            ],
            "没有在地图 41",
        ),
        (
            "customer_hint_purchase",
            [
                _observation_event(4, "This shop sells many ANTIDOTEs."),
                _observation_event(5, "No! POTIONs are all sold out."),
                _mid_frame(1, 42, party=((10, 20),), money=3000),
                _mid_frame(2, 41, party=((20, 20),), money=3000),
                _mid_frame(3, 42, party=((20, 20),), money=2900, bag={item_id("POKé BALL"): 1}),
            ],
            "买错",
        ),
        (
            "customer_hint_purchase",
            [
                _observation_event(4, "This shop sells many ANTIDOTEs."),
                _observation_event(5, "No! POTIONs are all sold out."),
                _mid_frame(1, 42, party=((10, 20),), money=3000),
                _mid_frame(2, 41, party=((20, 20),), money=3000),
                _mid_frame(3, 42, party=((20, 20),), money=2800, bag={item_id("ANTIDOTE"): 1}),
            ],
            "不是减少 100",
        ),
        (
            "customer_hint_purchase",
            [
                _mid_frame(1, 42, party=((10, 20),), money=3000),
                _mid_frame(2, 41, party=((20, 20),), money=3000),
                _observation_event(200, "This shop sells many ANTIDOTEs."),
                _observation_event(201, "No! POTIONs are all sold out."),
                _mid_frame(3, 42, party=((20, 20),), money=2900, bag={item_id("ANTIDOTE"): 1}),
            ],
            "顺序不对",
        ),
        (
            "cure_poison_budget",
            [
                _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
                _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=1900),
            ],
            "尚未治好",
        ),
        (
            "cure_poison_budget",
            [
                _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
                _mid_frame(2, 41, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
                _mid_frame(3, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1900),
            ],
            "进入宝可梦中心",
        ),
        (
            "cure_poison_budget",
            [
                _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
                _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=1800),
                _mid_frame(3, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1800),
            ],
            "不在 100–150",
        ),
        (
            "cure_poison_budget",
            [
                _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
                _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1900),
                _mid_frame(3, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1900),
            ],
            "先治后花钱",
        ),
    ],
)
def test_mid_rule_failure_branches_are_classified(
    check_id: str, events: list[ParsedEvent], reason_part: str
) -> None:
    verdict = judge(stream(*events), sample(check_id))

    assert verdict.outcome == "fail", verdict.reason
    assert reason_part in verdict.reason


def test_catch_then_heal_uses_party_growth_without_catch_dialog() -> None:
    ledger = stream(
        _mid_frame(1, 12, in_battle=True, party=((12, 25),), foe_hp=10),
        _mid_frame(2, 12, party=((12, 25), (8, 12)), foe_hp=10),
        _mid_frame(3, 41, party=((25, 25), (12, 12))),
        _mid_frame(4, 1, party=((25, 25), (12, 12))),
    )

    verdict = judge(ledger, sample("catch_then_heal"))

    assert verdict.outcome == "pass", verdict.reason


def test_catch_then_heal_does_not_accept_dialog_without_party_growth() -> None:
    ledger = stream(
        _mid_frame(1, 12, in_battle=True, party=((12, 25),), foe_hp=10),
        _mid_frame(
            2,
            12,
            in_battle=True,
            party=((12, 25),),
            foe_hp=10,
            dialog="All right! PIDGEY was caught!",
        ),
        _mid_frame(3, 41, party=((25, 25),)),
        _mid_frame(4, 1, party=((25, 25),)),
    )

    verdict = judge(ledger, sample("catch_then_heal"))

    assert verdict.outcome == "fail"
    assert "没抓到" in verdict.reason


def test_catch_then_heal_fails_when_party_growth_follows_healing() -> None:
    ledger = stream(
        _mid_frame(1, 12, in_battle=True, party=((12, 25),), foe_hp=10),
        _mid_frame(2, 41, party=((25, 25),)),
        _mid_frame(3, 12, party=((25, 25), (12, 12)), foe_hp=10),
        _mid_frame(4, 1, party=((25, 25), (12, 12))),
    )

    verdict = judge(ledger, sample("catch_then_heal"))

    assert verdict.outcome == "fail"
    assert "先治后抓" in verdict.reason


def test_cure_poison_budget_detects_center_only_in_script_observations() -> None:
    ledger = stream(
        _mid_frame(1, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=2000),
        _observation_event(4, "", observation_map_id=41),
        _mid_frame(2, 1, party=((20, 20), (10, 20)), status=("ok", "PSN"), money=1900),
        _mid_frame(3, 1, party=((20, 20), (10, 20)), status=("ok", "ok"), money=1900),
    )

    verdict = judge(ledger, sample("cure_poison_budget"))

    assert verdict.outcome == "fail"
    assert "曾进入宝可梦中心地图 41" in verdict.reason
