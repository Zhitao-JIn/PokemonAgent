"""接管脚本测评的用例表：存档、开跑前按的键、调哪条接管脚本、期望的结局与状态变化。"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from evals.scorers.world_script_execute.takeover_checks import (
    _bag,
    _battle_start,
    _box,
    _foe_hurt,
    _in_play,
    _knows,
    _left,
    _money,
    _order,
    _pc,
    _scene,
    _shop_start,
)
from pokemon_agent.world import TaskObservation, TaskScene
from pokemon_agent.world.scripts.execution_types import ScriptReason, ScriptStatus

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


class Case(BaseModel):
    """一个用例。`state` 相对 `experiment/experiment_states/`。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    case_id: str
    state: str
    script: str
    args: dict[str, str | int]
    status: ScriptStatus
    reason: ScriptReason | None = None
    pre: tuple[str, ...] = ()
    checks: tuple[Check, ...] = Field(default_factory=tuple)
    summary: str = ""
    """结果摘要里必须出现的一段话；空串不核。"""


BALL, POTION, MAP = "POKé BALL", "POTION", "TOWN MAP"
_UNCHANGED = (_money(0), _bag(BALL, 0), _bag(POTION, 0), _shop_start)
_S, _R = ScriptStatus, ScriptReason


__all__ = [
    "_money",
    "_bag",
    "_scene",
    "_left",
    "_battle_start",
    "_in_play",
    "_foe_hurt",
    "_shop_start",
    "_pc",
    "_order",
    "_box",
    "_knows",
    "TaskScene",
    "ScriptReason",
    "ScriptStatus",
    "Case",
    "BALL",
    "POTION",
    "MAP",
    "_UNCHANGED",
    "_S",
    "_R",
    "SHOP",
    "SHOP_LIST",
    "SHOP_QTY",
    "SHOP_CONFIRM",
    "KEYBOARD",
    "FIELD",
    "FOUR_MOVES",
    "LEARN",
    "PC",
    "BAG_OPEN",
    "PARTY_OPEN",
    "BATTLE",
    "LOW_HP",
    "FAINT",
]
