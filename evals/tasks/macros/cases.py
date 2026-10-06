"""宏测评的用例表：存档、开跑前按的键、调哪个宏、期望的结局与状态变化。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pokemon_agent.world import MacroReason, MacroStatus, TaskObservation, TaskScene

Check = Callable[[TaskObservation, TaskObservation], str]
"""`(开跑前, 收尾后)` 两帧 → 不符合期望时的一句话；符合为空串。"""

SHOP = "knowledge/knowledge_shop_open_buy_menu.state"
SHOP_LIST = "knowledge/knowledge_shop_select_item.state"
SHOP_QTY = "knowledge/knowledge_shop_confirm_purchase.state"
SHOP_CONFIRM = "knowledge/knowledge_shop_cancel_purchase.state"
KEYBOARD = "macros/player_keyboard.state"
FIELD = "macros/field_two_mons.state"
FOUR_MOVES = "macros/field_four_moves.state"
LEARN = "macros/learn_move.state"
PC = "knowledge/knowledge_pc_save.state"
BAG_OPEN = ("start", "a")
PARTY_OPEN = ("start", "up", "a")
BATTLE = "knowledge/knowledge_battle_pokemon_switch.state"
LOW_HP = "macros/battle_low_hp.state"
FAINT = "macros/battle_faint_switch.state"


@dataclass(frozen=True)
class Case:
    """一个用例。`state` 相对 `experiment/experiment_states/`。"""

    case_id: str
    state: str
    macro: str
    args: dict[str, str | int]
    status: MacroStatus
    reason: MacroReason | None = None
    pre: tuple[str, ...] = ()
    checks: tuple[Check, ...] = field(default_factory=tuple)
    summary: str = ""
    """结果摘要里必须出现的一段话；空串不核。"""


def _money(delta: int) -> Check:
    """金钱变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _shop(after).money - _shop(before).money
        return "" if got == delta else f"金钱变化 {got}，期望 {delta}"

    return check


def _bag(item: str, delta: int) -> Check:
    """背包里 `item` 的数量变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _count(after, item) - _count(before, item)
        return "" if got == delta else f"{item} 变化 {got}，期望 {delta}"

    return check


def _scene(scene: TaskScene) -> Check:
    """收尾后的场合。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        return "" if after.scene is scene else f"收尾场合 {after.scene.value}，期望 {scene.value}"

    return check


def _left(scene: TaskScene) -> Check:
    """收尾后已离开 `scene`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        return "" if after.scene is not scene else f"收尾仍在 {scene.value}"

    return check


def _battle_start(before: TaskObservation, after: TaskObservation) -> str:
    """收尾停在战斗行动菜单（FIGHT / PKMN / ITEM / RUN）。"""
    ok = after.scene is TaskScene.BATTLE_MENU and after.facts.cursor in (
        "FIGHT",
        "PKMN",
        "ITEM",
        "RUN",
    )
    return "" if ok else f"收尾不在行动菜单（{after.scene.value}，光标 {after.facts.cursor!r}）"


def _in_play(name: str) -> Check:
    """收尾时在场的是 `name`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        view = after.takeover
        mine = view.mine.name if view is not None and view.kind == "battle_menu" else ""
        return "" if mine == name else f"在场的是 {mine!r}，期望 {name}"

    return check


def _foe_hurt(before: TaskObservation, after: TaskObservation) -> str:
    """对手 HP 少了。"""
    hp0, hp1 = _foe_hp(before), _foe_hp(after)
    return "" if hp1 < hp0 else f"对手 HP {hp0}→{hp1}，没有少"


def _foe_hp(obs: TaskObservation) -> int:
    assert obs.takeover is not None and obs.takeover.kind == "battle_menu", "不在战斗选单"
    return obs.takeover.foe.hp


def _shop_start(before: TaskObservation, after: TaskObservation) -> str:
    """收尾停在商店主菜单（BUY / SELL / QUIT，实心光标，没有上一层的空心光标）。"""
    screen = after.facts.screen
    ok = "BUY" in screen and "▶" in screen and "▷" not in screen
    return "" if ok else "收尾不在商店主菜单"


def _shop(obs: TaskObservation):  # noqa: ANN202
    assert obs.takeover is not None and obs.takeover.kind == "shop_items", "不在商店"
    return obs.takeover


def _count(obs: TaskObservation, item: str) -> int:
    view = obs.takeover
    assert view is not None and hasattr(view, "bag"), "视图里没有背包"
    return sum(b.quantity for b in view.bag if b.name == item)


def _pc(item: str, delta: int) -> Check:
    """PC 里 `item` 的数量变化恰为 `delta`。"""

    def count(obs: TaskObservation) -> int:
        assert obs.takeover is not None and obs.takeover.kind == "pc", "不在 PC"
        return sum(b.quantity for b in obs.takeover.items if b.name == item)

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = count(after) - count(before)
        return "" if got == delta else f"PC 里 {item} 变化 {got}，期望 {delta}"

    return check


def _party_names(obs: TaskObservation) -> list[str]:
    view = obs.takeover
    assert view is not None and hasattr(view, "party"), "视图里没有队伍"
    return [m.name for m in view.party]


def _order(*names: str) -> Check:
    """收尾时队伍顺序。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = _party_names(after)
        return "" if got == list(names) else f"队伍顺序 {got}，期望 {list(names)}"

    return check


def _box(delta: int) -> Check:
    """当前箱只数变化恰为 `delta`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        got = len(after.takeover.box) - len(before.takeover.box)  # type: ignore[union-attr]
        return "" if got == delta else f"箱里只数变化 {got}，期望 {delta}"

    return check


def _knows(pokemon: str, move: str, *, yes: bool = True) -> Check:
    """收尾时 `pokemon` 会（或不会）`move`。"""

    def check(before: TaskObservation, after: TaskObservation) -> str:
        view = after.takeover
        assert view is not None and hasattr(view, "party"), "视图里没有队伍"
        mon = next((m for m in view.party if m.name == pokemon), None)
        knows = mon is not None and move in [x.name for x in mon.moves]
        return "" if knows == yes else f"{pokemon} {'不会' if yes else '会'} {move}"

    return check


BALL, POTION, MAP = "POKé BALL", "POTION", "TOWN MAP"
_UNCHANGED = (_money(0), _bag(BALL, 0), _bag(POTION, 0), _shop_start)
_S, _R = MacroStatus, MacroReason

CASES: list[Case] = [
    Case(
        "buy_ok",
        SHOP,
        "buy",
        {"item": BALL, "quantity": 5},
        _S.DONE,
        checks=(_money(-1000), _bag(BALL, 5), _shop_start),
    ),
    Case(
        "buy_lowercase_name",
        SHOP,
        "buy",
        {"item": "poke ball", "quantity": 1},
        _S.DONE,
        checks=(_money(-200), _bag(BALL, 1), _shop_start),
    ),
    Case(
        "buy_no_money",
        SHOP,
        "buy",
        {"item": BALL, "quantity": 99},
        _S.REJECTED,
        _R.NOT_ENOUGH_MONEY,
        checks=_UNCHANGED,
    ),
    Case(
        "buy_not_sold",
        SHOP,
        "buy",
        {"item": "MASTER BALL", "quantity": 1},
        _S.REJECTED,
        _R.UNKNOWN_ITEM,
        checks=_UNCHANGED,
    ),
    Case(
        "buy_qty_zero",
        SHOP,
        "buy",
        {"item": BALL, "quantity": 0},
        _S.REJECTED,
        _R.QUANTITY_OUT_OF_RANGE,
        checks=_UNCHANGED,
    ),
    Case(
        "buy_missing_arg", SHOP, "buy", {"item": BALL}, _S.REJECTED, _R.BAD_ARGS, checks=_UNCHANGED
    ),
    Case(
        "buy_from_list",
        SHOP_LIST,
        "buy",
        {"item": BALL, "quantity": 2},
        _S.DONE,
        checks=(_money(-400), _bag(BALL, 2), _shop_start),
    ),
    Case(
        "buy_from_quantity_box",
        SHOP_QTY,
        "buy",
        {"item": BALL, "quantity": 3},
        _S.DONE,
        checks=(_money(-600), _bag(BALL, 3), _shop_start),
    ),
    Case(
        "buy_from_yes_no",
        SHOP_CONFIRM,
        "buy",
        {"item": BALL, "quantity": 1},
        _S.DONE,
        checks=(_money(-200), _bag(BALL, 1), _shop_start),
    ),
    Case(
        "sell_ok",
        SHOP,
        "sell",
        {"item": POTION, "quantity": 1},
        _S.DONE,
        checks=(_money(150), _bag(POTION, -1), _shop_start),
    ),
    Case(
        "sell_not_in_bag",
        SHOP,
        "sell",
        {"item": "ANTIDOTE", "quantity": 1},
        _S.REJECTED,
        _R.NOT_IN_BAG,
        checks=_UNCHANGED,
    ),
    Case(
        "sell_too_many",
        SHOP,
        "sell",
        {"item": POTION, "quantity": 2},
        _S.REJECTED,
        _R.QUANTITY_OUT_OF_RANGE,
        checks=_UNCHANGED,
    ),
    Case(
        "sell_from_list",
        SHOP_LIST,
        "sell",
        {"item": POTION, "quantity": 1},
        _S.DONE,
        checks=(_money(150), _bag(POTION, -1), _shop_start),
    ),
    Case("quit_ok", SHOP, "quit", {}, _S.DONE, checks=(_left(TaskScene.SHOP_ITEMS),)),
    Case(
        "quit_from_quantity_box",
        SHOP_QTY,
        "quit",
        {},
        _S.DONE,
        checks=(_left(TaskScene.SHOP_ITEMS),),
    ),
    Case(
        "wrong_scene_macro",
        SHOP,
        "enter_name",
        {"name": "RED"},
        _S.REJECTED,
        _R.UNKNOWN_MACRO,
        checks=_UNCHANGED,
    ),
    Case(
        "fight_ok",
        BATTLE,
        "fight",
        {"move": "TACKLE"},
        _S.DONE,
        checks=(_foe_hurt, _battle_start),
        summary="停在选单",
    ),
    Case(
        "fight_lowercase",
        BATTLE,
        "fight",
        {"move": "tackle"},
        _S.DONE,
        checks=(_foe_hurt, _battle_start),
    ),
    Case(
        "fight_unknown_move",
        BATTLE,
        "fight",
        {"move": "EMBER"},
        _S.REJECTED,
        _R.UNKNOWN_MOVE,
        checks=(_battle_start,),
    ),
    Case(
        "fight_from_move_list",
        BATTLE,
        "fight",
        {"move": "GROWL"},
        _S.DONE,
        pre=("a",),
        checks=(_battle_start,),
    ),
    Case(
        "fight_stops_at_yes_no",
        LOW_HP,
        "fight",
        {"move": "GROWL"},
        _S.DONE,
        checks=(_scene(TaskScene.BATTLE),),
        summary="Use next",
    ),
    Case(
        "switch_ok",
        BATTLE,
        "switch",
        {"pokemon": "PIDGEY"},
        _S.DONE,
        checks=(_in_play("PIDGEY"), _battle_start),
    ),
    Case(
        "switch_active",
        BATTLE,
        "switch",
        {"pokemon": "BULBASAUR"},
        _S.REJECTED,
        _R.ALREADY_ACTIVE,
        checks=(_in_play("BULBASAUR"), _battle_start),
    ),
    Case(
        "switch_unknown",
        BATTLE,
        "switch",
        {"pokemon": "MEW"},
        _S.REJECTED,
        _R.UNKNOWN_POKEMON,
        checks=(_battle_start,),
    ),
    Case(
        "switch_from_party_list",
        BATTLE,
        "switch",
        {"pokemon": "PIDGEY"},
        _S.DONE,
        pre=("right", "a"),
        checks=(_in_play("PIDGEY"), _battle_start),
    ),
    Case(
        "use_potion_ok",
        LOW_HP,
        "use_item",
        {"item": POTION, "pokemon": "BULBASAUR"},
        _S.DONE,
        summary="用 POTION（对 BULBASAUR）",
    ),
    Case(
        "use_potion_full_hp",
        BATTLE,
        "use_item",
        {"item": POTION, "pokemon": "BULBASAUR"},
        _S.REJECTED,
        _R.CANNOT_USE,
        checks=(_battle_start,),
    ),
    Case(
        "use_potion_no_target",
        BATTLE,
        "use_item",
        {"item": POTION},
        _S.REJECTED,
        _R.TARGET_REQUIRED,
        checks=(_battle_start,),
    ),
    Case(
        "use_item_not_in_bag",
        BATTLE,
        "use_item",
        {"item": "GREAT BALL"},
        _S.REJECTED,
        _R.NOT_IN_BAG,
        checks=(_battle_start,),
    ),
    Case("use_ball", BATTLE, "use_item", {"item": BALL}, _S.DONE, summary="用 POKé BALL"),
    Case(
        "use_ball_from_bag_list",
        BATTLE,
        "use_item",
        {"item": BALL},
        _S.DONE,
        pre=("down", "a"),
        summary="用 POKé BALL",
    ),
    Case("run_ok", BATTLE, "run", {}, _S.DONE, summary="逃走了"),
    Case(
        "send_out_ok",
        FAINT,
        "send_out",
        {"pokemon": "PIDGEY"},
        _S.DONE,
        checks=(_in_play("PIDGEY"), _battle_start),
    ),
    Case(
        "send_out_fainted",
        FAINT,
        "send_out",
        {"pokemon": "BULBASAUR"},
        _S.REJECTED,
        _R.POKEMON_FAINTED,
        checks=(_scene(TaskScene.FAINT_SWITCH),),
    ),
    Case(
        "send_out_unknown",
        FAINT,
        "send_out",
        {"pokemon": "MEW"},
        _S.REJECTED,
        _R.UNKNOWN_POKEMON,
        checks=(_scene(TaskScene.FAINT_SWITCH),),
    ),
    Case(
        "battle_macro_in_shop",
        SHOP,
        "fight",
        {"move": "TACKLE"},
        _S.REJECTED,
        _R.UNKNOWN_MACRO,
        checks=_UNCHANGED,
    ),
    Case(
        "name_ok",
        KEYBOARD,
        "enter_name",
        {"name": "ZHITAO"},
        _S.DONE,
        checks=(_left(TaskScene.NAMING),),
    ),
    Case(
        "name_after_typing",
        KEYBOARD,
        "enter_name",
        {"name": "ASH"},
        _S.DONE,
        pre=("a", "right", "a", "select", "a"),
        checks=(_left(TaskScene.NAMING),),
    ),
    Case(
        "name_lowercase",
        KEYBOARD,
        "enter_name",
        {"name": "zhitao"},
        _S.REJECTED,
        _R.INVALID_NAME,
        checks=(_scene(TaskScene.NAMING),),
    ),
    Case(
        "name_too_long",
        KEYBOARD,
        "enter_name",
        {"name": "ABCDEFGH"},
        _S.REJECTED,
        _R.INVALID_NAME,
        checks=(_scene(TaskScene.NAMING),),
    ),
    Case(
        "name_empty",
        KEYBOARD,
        "enter_name",
        {"name": ""},
        _S.REJECTED,
        _R.INVALID_NAME,
        checks=(_scene(TaskScene.NAMING),),
    ),
    # ---- 背包（野外）----
    Case(
        "use_potion_field",
        FIELD,
        "use",
        {"item": POTION, "pokemon": "BB?!"},
        _S.DONE,
        pre=BAG_OPEN,
        checks=(_bag(POTION, -1), _scene(TaskScene.BAG)),
        summary="HP 16→26",
    ),
    Case(
        "use_status_no_effect",
        FIELD,
        "use",
        {"item": "ANTIDOTE", "pokemon": "BB?!"},
        _S.REJECTED,
        _R.CANNOT_USE,
        pre=BAG_OPEN,
        checks=(_bag("ANTIDOTE", 0),),
    ),
    Case(
        "use_unsupported_item",
        FIELD,
        "use",
        {"item": MAP},
        _S.REJECTED,
        _R.CANNOT_USE,
        pre=BAG_OPEN,
    ),
    Case(
        "use_from_submenu",
        FIELD,
        "use",
        {"item": POTION, "pokemon": "BB?!"},
        _S.DONE,
        pre=(*BAG_OPEN, "a"),
        checks=(_bag(POTION, -1),),
    ),
    Case(
        "use_rare_candy_to_learn",
        FOUR_MOVES,
        "use",
        {"item": "RARE CANDY", "pokemon": "BB?!"},
        _S.DONE,
        pre=BAG_OPEN,
        checks=(_scene(TaskScene.LEARN_MOVE),),
    ),
    Case(
        "toss_ok",
        FIELD,
        "toss",
        {"item": BALL, "quantity": 2},
        _S.DONE,
        pre=BAG_OPEN,
        checks=(_bag(BALL, -2), _scene(TaskScene.BAG)),
    ),
    Case(
        "toss_key_item",
        FIELD,
        "toss",
        {"item": MAP, "quantity": 1},
        _S.REJECTED,
        _R.KEY_ITEM,
        pre=BAG_OPEN,
        checks=(_bag(MAP, 0),),
    ),
    Case(
        "toss_too_many",
        FIELD,
        "toss",
        {"item": BALL, "quantity": 5},
        _S.REJECTED,
        _R.QUANTITY_OUT_OF_RANGE,
        pre=BAG_OPEN,
    ),
    Case(
        "toss_from_quantity_box",
        FIELD,
        "toss",
        {"item": BALL, "quantity": 1},
        _S.DONE,
        pre=(*BAG_OPEN, "down", "a", "down", "a"),
        checks=(_bag(BALL, -1),),
    ),
    Case(
        "bag_close",
        FIELD,
        "close",
        {},
        _S.DONE,
        pre=BAG_OPEN,
        checks=(_scene(TaskScene.START_MENU),),
    ),
    # ---- 队伍（野外）----
    Case(
        "party_switch_ok",
        FIELD,
        "switch",
        {"a": "BB?!", "b": "PP!?"},
        _S.DONE,
        pre=PARTY_OPEN,
        checks=(_order("PP!?", "BB?!"),),
    ),
    Case(
        "party_switch_same",
        FIELD,
        "switch",
        {"a": "BB?!", "b": "bb?!"},
        _S.REJECTED,
        _R.BAD_ARGS,
        pre=PARTY_OPEN,
        checks=(_order("BB?!", "PP!?"),),
    ),
    Case(
        "party_switch_unknown",
        FIELD,
        "switch",
        {"a": "BB?!", "b": "MEW"},
        _S.REJECTED,
        _R.UNKNOWN_POKEMON,
        pre=PARTY_OPEN,
    ),
    Case(
        "party_switch_from_submenu",
        FIELD,
        "switch",
        {"a": "PP!?", "b": "BB?!"},
        _S.DONE,
        pre=(*PARTY_OPEN, "a"),
        checks=(_order("PP!?", "BB?!"),),
    ),
    Case(
        "party_stats",
        FIELD,
        "stats",
        {"pokemon": "PP!?"},
        _S.DONE,
        pre=PARTY_OPEN,
        checks=(_scene(TaskScene.POKEMON_INFO),),
    ),
    Case(
        "field_move_unknown",
        FIELD,
        "field_move",
        {"pokemon": "BB?!", "move": "CUT"},
        _S.REJECTED,
        _R.UNKNOWN_MOVE,
        pre=PARTY_OPEN,
    ),
    Case(
        "field_move_fly",
        FIELD,
        "field_move",
        {"pokemon": "PP!?", "move": "FLY"},
        _S.REJECTED,
        _R.CANNOT_USE,
        pre=PARTY_OPEN,
    ),
    Case(
        "party_close",
        FIELD,
        "close",
        {},
        _S.DONE,
        pre=PARTY_OPEN,
        checks=(_scene(TaskScene.START_MENU),),
    ),
    # ---- PC（存档停在比尔的 PC 菜单：每例都从中途开跑）----
    Case(
        "withdraw_item_ok",
        PC,
        "withdraw_item",
        {"item": POTION, "quantity": 1},
        _S.DONE,
        checks=(_bag(POTION, 1), _pc(POTION, -1)),
    ),
    Case(
        "withdraw_item_missing",
        PC,
        "withdraw_item",
        {"item": BALL, "quantity": 1},
        _S.REJECTED,
        _R.NOT_IN_BAG,
    ),
    Case(
        "deposit_item_ok",
        PC,
        "deposit_item",
        {"item": BALL, "quantity": 2},
        _S.DONE,
        checks=(_bag(BALL, -2), _pc(BALL, 2)),
    ),
    Case(
        "deposit_key_item",
        PC,
        "deposit_item",
        {"item": MAP, "quantity": 1},
        _S.DONE,
        checks=(_bag(MAP, -1), _pc(MAP, 1)),
    ),
    Case(
        "deposit_item_too_many",
        PC,
        "deposit_item",
        {"item": BALL, "quantity": 9},
        _S.REJECTED,
        _R.QUANTITY_OUT_OF_RANGE,
    ),
    Case(
        "toss_item_ok",
        PC,
        "toss_item",
        {"item": POTION, "quantity": 1},
        _S.DONE,
        checks=(_pc(POTION, -1), _bag(POTION, 0)),
    ),
    Case(
        "deposit_pokemon_ok",
        PC,
        "deposit_pokemon",
        {"pokemon": "PIDGEY"},
        _S.DONE,
        checks=(_box(1),),
    ),
    Case(
        "withdraw_pokemon_missing",
        PC,
        "withdraw_pokemon",
        {"pokemon": "MEW"},
        _S.REJECTED,
        _R.UNKNOWN_POKEMON,
    ),
    Case("change_box_ok", PC, "change_box", {"n": 3}, _S.DONE, summary="BOX 3"),
    Case("change_box_range", PC, "change_box", {"n": 13}, _S.REJECTED, _R.QUANTITY_OUT_OF_RANGE),
    Case("pc_log_off", PC, "log_off", {}, _S.DONE, checks=(_left(TaskScene.PC),)),
    # ---- 学新招 ----
    Case(
        "forget_ok",
        LEARN,
        "forget",
        {"move": "GUST"},
        _S.DONE,
        checks=(_knows("BB?!", "VINE WHIP"), _knows("BB?!", "GUST", yes=False)),
    ),
    Case(
        "forget_unknown_move",
        LEARN,
        "forget",
        {"move": "EMBER"},
        _S.REJECTED,
        _R.UNKNOWN_MOVE,
        checks=(_scene(TaskScene.LEARN_MOVE),),
    ),
    Case(
        "forget_from_abandon",
        LEARN,
        "forget",
        {"move": "TACKLE"},
        _S.DONE,
        pre=("down", "a"),
        checks=(_knows("BB?!", "VINE WHIP"),),
    ),
    Case(
        "forget_from_move_list",
        LEARN,
        "forget",
        {"move": "GROWL"},
        _S.DONE,
        pre=("a",),
        checks=(_knows("BB?!", "VINE WHIP"), _knows("BB?!", "GROWL", yes=False)),
    ),
    Case(
        "skip_ok",
        LEARN,
        "skip",
        {},
        _S.DONE,
        checks=(_knows("BB?!", "VINE WHIP", yes=False),),
        summary="不学 VINE WHIP",
    ),
]
"""全部用例；`case_id` 唯一。"""

__all__ = ["CASES", "Case"]
