"""接管视图测评的用例：存档、开跑前按的键、期望场合、视图字段的期望值（点路径 → 值）、
屏上必现的字。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pokemon_agent.world import TaskScene

SHOP = "knowledge/knowledge_shop_open_buy_menu.state"
BATTLE = "knowledge/knowledge_battle_pokemon_switch.state"
FAINT = "macros/battle_faint_switch.state"
FIELD = "macros/field_two_mons.state"
PC = "knowledge/knowledge_pc_save.state"
LEARN = "macros/learn_move.state"
KEYBOARD = "macros/player_keyboard.state"


@dataclass(frozen=True)
class ViewCase:
    """一个用例。`state` 相对 `experiment/experiment_states/`。"""

    case_id: str
    state: str
    scene: TaskScene
    expect: dict[str, object]
    pre: tuple[str, ...] = ()
    on_screen: tuple[str, ...] = field(default_factory=tuple)


CASES: list[ViewCase] = [
    ViewCase(
        "shop_items",
        SHOP,
        TaskScene.SHOP_ITEMS,
        {
            "items.0.name": "POKé BALL",
            "items.0.price": 200,
            "items.1.name": "ANTIDOTE",
            "items.1.price": 100,
            "items.2.name": "PARLYZ HEAL",
            "items.2.price": 200,
            "items.3.name": "BURN HEAL",
            "items.3.price": 250,
            "money": 3000,
            "bag.0.name": "POTION",
            "bag.0.quantity": 1,
        },
        on_screen=("¥3000",),
    ),
    ViewCase(
        "naming",
        KEYBOARD,
        TaskScene.NAMING,
        {"target": "YOUR NAME?", "typed": ""},
        on_screen=("YOUR NAME?",),
    ),
    ViewCase(
        "battle_menu",
        BATTLE,
        TaskScene.BATTLE_MENU,
        {
            "mine.name": "BULBASAUR",
            "mine.level": 7,
            "mine.hp": 25,
            "mine.max_hp": 25,
            "mine.moves.0.name": "TACKLE",
            "mine.moves.1.name": "GROWL",
            "mine.moves.2.name": "LEECH SEED",
            "foe.name": "PIDGEY",
            "foe.level": 3,
            "trainer": False,
            "party.0.name": "BULBASAUR",
            "party.0.active": True,
            "party.1.name": "PIDGEY",
            "party.1.active": False,
            "bag.0.name": "POTION",
            "bag.1.name": "POKé BALL",
            "bag.1.quantity": 4,
        },
        on_screen=("BULBASAUR", "PIDGEY", "25/ 25"),
    ),
    ViewCase(
        "faint_switch",
        FAINT,
        TaskScene.BATTLE_SWITCH,
        {
            "party.0.name": "BULBASAUR",
            "party.0.hp": 0,
            "party.1.name": "PIDGEY",
            "party.1.hp": 15,
            "party.1.max_hp": 15,
        },
        on_screen=("BULBASAUR", "FNT", "15/ 15"),
    ),
    ViewCase(
        "bag",
        FIELD,
        TaskScene.BAG,
        {
            "bag.0.name": "POTION",
            "bag.1.name": "TOWN MAP",
            "bag.2.name": "POKé BALL",
            "bag.2.quantity": 3,
            "party.0.name": "BB?!",
            "party.0.hp": 16,
            "party.0.max_hp": 26,
            "party.1.name": "PP!?",
            "party.1.hp": 9,
        },
        pre=("start", "a"),
        on_screen=("POTION", "TOWN MAP"),
    ),
    ViewCase(
        "party",
        FIELD,
        TaskScene.PARTY,
        {
            "party.0.name": "BB?!",
            "party.0.level": 8,
            "party.0.hp": 16,
            "party.0.max_hp": 26,
            "party.1.name": "PP!?",
            "party.1.level": 6,
            "party.1.hp": 9,
            "party.1.max_hp": 20,
        },
        pre=("start", "up", "a"),
        on_screen=("BB?!", "PP!?", "16/ 26", " 9/ 20"),
    ),
    ViewCase(
        "pc",
        PC,
        TaskScene.PC,
        {
            "items.0.name": "POTION",
            "items.0.quantity": 1,
            "bag.0.name": "TOWN MAP",
            "bag.1.name": "POKé BALL",
            "box": [],
            "box_number": 1,
            "party.0.name": "BULBASAUR",
            "party.1.name": "PIDGEY",
        },
        on_screen=("BOX No. 1",),
    ),
    ViewCase(
        "learn_move",
        LEARN,
        TaskScene.LEARN_MOVE,
        {
            "pokemon": "BB?!",
            "new_move": "VINE WHIP",
            "moves.0.name": "TACKLE",
            "moves.1.name": "GROWL",
            "moves.2.name": "LEECH SEED",
            "moves.3.name": "GUST",
        },
        on_screen=("VINE WHIP", "BB?!"),
    ),
]
"""全部用例；`case_id` 唯一。"""

__all__ = ["CASES", "ViewCase"]
