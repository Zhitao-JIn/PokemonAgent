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
from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import EpisodeStartContent, EventMeta, SenseFrameContent
from pokemon_agent.world import Facts, PlaceInWorld, RamReadout
from pokemon_agent.world.interface import (
    BagItem,
    BattleStatus,
    Combatant,
    DecodedText,
    MenuVars,
    PartyMon,
)

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
    details: str = "",
    source: str = "decode",
    in_battle: bool = False,
    money: int = 3000,
    bag: dict[int, int] | None = None,
    party: tuple[tuple[int, int], ...] = ((20, 20),),
    my_hp: int = 20,
    foe_hp: int = 15,
) -> ParsedEvent:
    """一帧 `sense_frame`：位置、文字、内存读数都可指定。

    `source="vlm"` 模拟 episode 层看档帧上视觉抄出了字、屏幕解码却没有：文字只进 `facts`，
    `ram.decoded` 为空——判据读的是后者。
    """
    extra = {"option_details": details} if details else {}
    facts = Facts(
        map_id=map_id,
        dialog_text=dialog,
        options=list(options),
        cursor=cursor,
        overlay=overlay,
        **extra,
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
        party=[PartyMon(species=153, level=5, hp=h, max_hp=m, status="ok") for h, m in party],
        battle=battle,
        decoded=DecodedText(dialog_text=dialog, options=list(options), cursor=cursor or "")
        if source == "decode"
        else DecodedText(dialog_text="", options=[], cursor=""),
    )
    content = SenseFrameContent(
        status="s", facts=facts, done=False,
        place=PlaceInWorld(map_id=map_id, x=3, y=y), ram=ram,
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


def stream(*frames: ParsedEvent) -> RunStream:
    """一局：开局账 + 这些帧。"""
    start = EpisodeStartContent(goal_id=GOAL, goal="g", success_criteria="c", max_steps=15)
    return RunStream([_event("episode_start", 0, start), *frames])


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
            frame(2, options=("POKé BALL", "CANCEL"), cursor="POKé BALL", details="POKé BALL ¥200"),
        ],
        [frame(1), frame(2, options=("BUY", "SELL", "QUIT"), cursor="BUY")],
    ),
    "shop_item_selected": (
        [frame(1), frame(2, options=("YES", "NO"), cursor="YES")],
        [
            frame(1),
            frame(2, options=("POKé BALL", "CANCEL"), cursor="POKé BALL", details="POKé BALL ¥200"),
        ],
    ),
    "shop_bought": (
        [frame(1, money=3000, bag={4: 1}), frame(2, money=2800, bag={4: 2})],
        [
            frame(1, money=3000, bag={4: 1}),
            frame(2, money=3000, bag={4: 1}, dialog="Here you are! Thank you!"),
        ],
    ),
    "shop_cancelled": (
        [
            frame(1, options=("YES", "NO")),
            frame(2, options=("POKé BALL",), details="POKé BALL ¥200"),
        ],
        [
            frame(1, money=3000, options=("YES", "NO")),
            frame(2, money=2800, options=("POKé BALL",), details="POKé BALL ¥200"),
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
    samples = load(rule_ids=set(RULES))
    switch = next(s for s in samples if s.sample_id == "knowledge_battle_pokemon_switch")

    assert switch.check_id == "party_list_opened_in_battle"
    assert switch.check_id in RULES
